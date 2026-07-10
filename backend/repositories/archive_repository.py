"""Internet Archive client - the Free Music download source.

Only surfaces items carrying an explicit Creative Commons or public-domain
``licenseurl``. That filter is DroppedNeedle's own editorial rule for its own
client (D24/D25); it is not imposed on anyone else.

See ``ARCHIVE_API_NOTES.md`` for the live-probed shapes this depends on.
"""

import logging
from typing import Any, AsyncIterator, Callable
from urllib.parse import quote

import httpx
import msgspec

from core.exceptions import ExternalServiceError, RateLimitedError
from infrastructure.msgspec_fastapi import AppStruct
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter
from infrastructure.resilience.retry import CircuitBreaker, CircuitOpenError, with_retry
from infrastructure.service_health import report_breaker_health

logger = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"

# The Archive publishes no documented rate limit for these endpoints. 2/s with a
# small burst is well under what its own tooling (internetarchive CLI) issues,
# and a Free Music search runs at most once per request.
_rate_limiter = TokenBucketRateLimiter(rate=2.0, capacity=4)

_archive_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="archive",
    on_state_change=report_breaker_health(
        "archive",
        "Free Music",
        message="The Internet Archive is temporarily unavailable.",
    ),
)

# Licence prefixes we accept. Anything else (or absent) is not surfaced.
_ALLOWED_LICENCE_PREFIXES = (
    "http://creativecommons.org/licenses/",
    "https://creativecommons.org/licenses/",
    "http://creativecommons.org/publicdomain/",
    "https://creativecommons.org/publicdomain/",
)

# Archive `format` strings for audio we can import, mapped to a file extension.
_AUDIO_FORMATS = {
    "flac": "flac",
    "24bit flac": "flac",
    "vbr mp3": "mp3",
    "mp3": "mp3",
    "ogg vorbis": "ogg",
}


class ArchiveError(ExternalServiceError):
    """The Internet Archive could not be reached or returned nonsense."""


class ArchiveItem(AppStruct):
    """One search hit, already licence-filtered."""

    identifier: str
    title: str
    creator: str = ""
    year: int | None = None
    licence_url: str = ""


class ArchiveFile(AppStruct):
    name: str
    format: str
    size_bytes: int = 0
    track: int | None = None
    title: str = ""


def is_open_licence(licence_url: str | None) -> bool:
    """True only for an explicit Creative Commons or public-domain licence."""
    value = (licence_url or "").strip().lower()
    return bool(value) and value.startswith(_ALLOWED_LICENCE_PREFIXES)


def _escape(value: str) -> str:
    """Escape a value for a Lucene phrase query."""
    return value.replace("\\", "").replace('"', "")


class ArchiveRepository:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @staticmethod
    def reset_circuit_breaker() -> None:
        _archive_circuit_breaker.reset()

    async def search_audio(self, artist: str, title: str, limit: int = 12) -> list[ArchiveItem]:
        """Licensed audio items matching artist + title. Absence is ``[]``; a dead
        Archive raises, because Free Music failing is a real failure the user is
        waiting on, not a degradable enrichment."""
        clauses = ["mediatype:audio", "licenseurl:[* TO *]"]
        if artist.strip():
            clauses.append(f'creator:"{_escape(artist)}"')
        if title.strip():
            clauses.append(f'title:"{_escape(title)}"')
        if len(clauses) == 2:
            return []

        data = await self._search(" AND ".join(clauses), limit)
        items: list[ArchiveItem] = []
        for doc in data.get("response", {}).get("docs", []):
            identifier = doc.get("identifier")
            licence = doc.get("licenseurl")
            if not identifier or not is_open_licence(licence):
                continue
            creator = doc.get("creator")
            if isinstance(creator, list):
                creator = ", ".join(str(c) for c in creator)
            year = doc.get("year")
            items.append(
                ArchiveItem(
                    identifier=str(identifier),
                    title=str(doc.get("title") or identifier),
                    creator=str(creator or ""),
                    year=int(year) if str(year or "").isdigit() else None,
                    licence_url=str(licence),
                )
            )
        return items

    async def get_item_files(self, identifier: str) -> tuple[str, list[ArchiveFile]]:
        """``(licence_url, audio_files)`` for an item. A dark or removed item
        returns ``("", [])`` - the Archive answers ``{}`` for those."""
        data = await self._metadata(identifier)
        metadata = data.get("metadata") or {}
        licence = str(metadata.get("licenseurl") or "")
        if not is_open_licence(licence):
            return "", []

        files: list[ArchiveFile] = []
        for entry in data.get("files") or []:
            fmt = str(entry.get("format") or "").lower()
            name = entry.get("name")
            if not name or fmt not in _AUDIO_FORMATS:
                continue
            files.append(
                ArchiveFile(
                    name=str(name),
                    format=fmt,
                    size_bytes=int(entry.get("size") or 0),
                    track=int(entry["track"]) if str(entry.get("track") or "").isdigit() else None,
                    title=str(entry.get("title") or ""),
                )
            )
        return licence, files

    async def stream_file(
        self, identifier: str, filename: str
    ) -> AsyncIterator[bytes]:
        """Yield a file's bytes. Raises ``ArchiveError`` on a non-200."""
        url = DOWNLOAD_URL.format(identifier=identifier, filename=quote(filename))
        async with self._client.stream("GET", url, follow_redirects=True) as response:
            if response.status_code == 429:
                raise RateLimitedError("Internet Archive rate limited", retry_after_seconds=60)
            if response.status_code != 200:
                raise ArchiveError(
                    f"Internet Archive returned HTTP {response.status_code} for a file"
                )
            async for chunk in response.aiter_bytes():
                yield chunk

    @staticmethod
    def extension_for(archive_format: str) -> str:
        return _AUDIO_FORMATS.get(archive_format.lower(), "")

    @with_retry(
        max_attempts=2,
        circuit_breaker=_archive_circuit_breaker,
        retriable_exceptions=(httpx.TimeoutException, httpx.TransportError),
    )
    async def _search(self, query: str, limit: int) -> dict[str, Any]:
        await _rate_limiter.acquire()
        response = await self._get(
            SEARCH_URL,
            params=[
                ("q", query),
                ("fl[]", "identifier"),
                ("fl[]", "title"),
                ("fl[]", "creator"),
                ("fl[]", "licenseurl"),
                ("fl[]", "year"),
                ("rows", str(max(1, min(limit, 50)))),
                ("output", "json"),
            ],
        )
        return _decode(response)

    @with_retry(
        max_attempts=2,
        circuit_breaker=_archive_circuit_breaker,
        retriable_exceptions=(httpx.TimeoutException, httpx.TransportError),
    )
    async def _metadata(self, identifier: str) -> dict[str, Any]:
        await _rate_limiter.acquire()
        response = await self._get(METADATA_URL.format(identifier=quote(identifier)))
        return _decode(response)

    async def _get(self, url: str, params: Any = None) -> httpx.Response:
        try:
            response = await self._client.get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError):
            raise  # @with_retry owns these; wrapping them would disable the retry
        except httpx.HTTPError as exc:
            raise ArchiveError(f"Internet Archive transport error: {exc}") from exc
        if response.status_code == 429:
            raise RateLimitedError("Internet Archive rate limited", retry_after_seconds=60)
        if response.status_code != 200:
            raise ArchiveError(f"Internet Archive returned HTTP {response.status_code}")
        return response


def _decode(response: httpx.Response) -> dict[str, Any]:
    try:
        return msgspec.json.decode(response.content, type=dict[str, Any])
    except msgspec.DecodeError as exc:
        raise ArchiveError("Internet Archive returned invalid JSON") from exc
