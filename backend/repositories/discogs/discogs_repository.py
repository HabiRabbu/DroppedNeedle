import logging
import re
import time
from collections import defaultdict

import httpx
import msgspec

from core.exceptions import DiscogsApiError, RateLimitedError
from infrastructure.cache.cache_keys import discogs_release_key, discogs_search_key
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.degradation import try_get_degradation_context
from infrastructure.http.deduplication import RequestDeduplicator
from infrastructure.integration_result import IntegrationResult
from infrastructure.queue.priority_queue import RequestPriority, get_priority_queue
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter
from infrastructure.resilience.retry import CircuitBreaker, CircuitOpenError, with_retry
from infrastructure.service_health import report_breaker_health
from models.library_contribution import (
    DiscogsArtistCredit,
    DiscogsFormat,
    DiscogsIdentifier,
    DiscogsLabel,
    DiscogsMedium,
    DiscogsRelease,
    DiscogsReleaseCandidate,
    DiscogsTrack,
)
from repositories.discogs.discogs_models import (
    DiscogsWireArtist,
    DiscogsWireRelease,
    DiscogsWireSearchResponse,
    DiscogsWireTrack,
)

logger = logging.getLogger(__name__)

DISCOGS_API_BASE = "https://api.discogs.com"
DISCOGS_WEB_BASE = "https://www.discogs.com"
DISCOGS_CACHE_SECONDS = 6 * 60 * 60
_SOURCE = "discogs"


class _DiscogsTransientError(DiscogsApiError):
    pass


_discogs_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="discogs",
    on_state_change=report_breaker_health(
        "discogs",
        "contribution metadata",
        message="Optional Discogs contribution metadata is temporarily unavailable.",
    ),
)

# Live unauthenticated responses advertised 25 requests/minute on 2026-07-21.
# See repositories/discogs/discogs_API_NOTES.md. Capacity 1 prevents a burst.
_discogs_rate_limiter = TokenBucketRateLimiter(rate=25 / 60, capacity=1)
_discogs_deduplicator = RequestDeduplicator()

_POSITION_DISC_TRACK = re.compile(r"^(?P<disc>\d+)[-.](?P<track>\d+)$")
_POSITION_NUMBER = re.compile(r"^\d+$")
_POSITION_SIDE = re.compile(r"^(?P<side>[A-Z])(?P<track>\d*)$", re.IGNORECASE)


def _record_degradation(message: str) -> None:
    context = try_get_degradation_context()
    if context is not None:
        context.record(IntegrationResult.error(source=_SOURCE, msg=message))


def _retry_after(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    try:
        return max(1.0, float(value)) if value is not None else 60.0
    except ValueError:
        return 60.0


def _duration_seconds(value: str) -> float | None:
    if not value:
        return None
    parts = value.strip().split(":")
    if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60):
        return None
    if len(numbers) == 2:
        return float(numbers[0] * 60 + numbers[1])
    return float(numbers[0] * 3600 + numbers[1] * 60 + numbers[2])


def _artist_credit(artist: DiscogsWireArtist) -> DiscogsArtistCredit:
    artist_id = str(artist.id) if artist.id is not None else None
    return DiscogsArtistCredit(
        name=artist.name or artist.anv,
        credited_name=artist.anv or None,
        join_phrase=artist.join,
        artist_id=artist_id,
        canonical_url=(
            f"{DISCOGS_WEB_BASE}/artist/{artist_id}" if artist_id is not None else None
        ),
    )


def _position(value: str, fallback: int) -> tuple[int, int | None]:
    stripped = value.strip().upper()
    match = _POSITION_DISC_TRACK.fullmatch(stripped)
    if match:
        return max(1, int(match.group("disc"))), int(match.group("track"))
    if _POSITION_NUMBER.fullmatch(stripped):
        return 1, int(stripped)
    match = _POSITION_SIDE.fullmatch(stripped)
    if match:
        side_index = ord(match.group("side").upper()) - ord("A")
        medium = max(1, side_index // 2 + 1)
        number = int(match.group("track")) if match.group("track") else fallback
        return medium, number
    return 1, None


def _flatten_tracks(rows: list[DiscogsWireTrack]) -> list[DiscogsWireTrack]:
    flattened: list[DiscogsWireTrack] = []
    for row in rows:
        flattened.append(row)
        flattened.extend(_flatten_tracks(row.sub_tracks))
    return flattened


def _normalize_media(
    tracks: list[DiscogsWireTrack], formats: list[DiscogsFormat]
) -> list[DiscogsMedium]:
    grouped: dict[int, list[DiscogsTrack]] = defaultdict(list)
    counters: dict[int, int] = defaultdict(int)
    for row in _flatten_tracks(tracks):
        fallback = counters[1] + 1
        medium_position, number = _position(row.position, fallback)
        counters[medium_position] += 1
        if number is None and row.type_.casefold() == "track":
            number = counters[medium_position]
        grouped[medium_position].append(
            DiscogsTrack(
                source_position=row.position or None,
                number=number,
                title=row.title,
                duration_seconds=_duration_seconds(row.duration),
                heading=row.type_.casefold() != "track",
                artists=[_artist_credit(artist) for artist in row.artists],
            )
        )
    format_name = formats[0].name if formats else None
    return [
        DiscogsMedium(
            position=position,
            format=format_name,
            tracks=grouped[position],
        )
        for position in sorted(grouped)
    ]


def _normalized_formats(release: DiscogsWireRelease) -> list[DiscogsFormat]:
    result: list[DiscogsFormat] = []
    for item in release.formats:
        try:
            quantity = int(item.qty) if item.qty else None
        except ValueError:
            quantity = None
        result.append(
            DiscogsFormat(
                name=item.name,
                quantity=quantity,
                descriptions=item.descriptions,
                text=item.text or None,
            )
        )
    return result


def normalize_release(
    release: DiscogsWireRelease, *, fetched_at: float
) -> DiscogsRelease:
    if release.id <= 0 or not release.title:
        raise DiscogsApiError("Discogs returned an incomplete release.")
    formats = _normalized_formats(release)
    identifiers = [
        DiscogsIdentifier(
            type=item.type,
            value=item.value,
            description=item.description or None,
        )
        for item in release.identifiers
        if item.type and item.value
    ]
    barcode = next(
        (
            item.value.replace(" ", "").replace("-", "")
            for item in identifiers
            if item.type.casefold() == "barcode"
        ),
        None,
    )
    return DiscogsRelease(
        release_id=str(release.id),
        master_id=str(release.master_id) if release.master_id else None,
        canonical_release_url=f"{DISCOGS_WEB_BASE}/release/{release.id}",
        canonical_master_url=(
            f"{DISCOGS_WEB_BASE}/master/{release.master_id}"
            if release.master_id
            else None
        ),
        title=release.title,
        artist_name=release.artists_sort
        or ", ".join(artist.name for artist in release.artists if artist.name),
        artists=[_artist_credit(artist) for artist in release.artists],
        released_date=release.released or None,
        year=release.year,
        country=release.country or None,
        labels=[
            DiscogsLabel(
                name=label.name,
                catalogue_number=label.catno or None,
                label_id=str(label.id) if label.id is not None else None,
                canonical_url=(
                    f"{DISCOGS_WEB_BASE}/label/{label.id}"
                    if label.id is not None
                    else None
                ),
            )
            for label in release.labels
            if label.name
        ],
        identifiers=identifiers,
        barcode=barcode,
        formats=formats,
        media=_normalize_media(release.tracklist, formats),
        source_fetched_at=fetched_at,
    )


class DiscogsRepository:
    def __init__(self, http_client: httpx.AsyncClient, cache: CacheInterface) -> None:
        self._client = http_client
        self._cache = cache

    @staticmethod
    def reset_circuit_breaker() -> None:
        _discogs_circuit_breaker.reset()

    @with_retry(
        max_attempts=3,
        base_delay=1.0,
        max_delay=4.0,
        circuit_breaker=_discogs_circuit_breaker,
        retriable_exceptions=(
            httpx.HTTPError,
            _DiscogsTransientError,
            RateLimitedError,
        ),
        non_breaking_exceptions=(RateLimitedError,),
    )
    async def _request(
        self,
        path: str,
        *,
        params: dict[str, str] | None,
        priority: RequestPriority,
        decode_type: type,
    ):
        semaphore = await get_priority_queue().acquire_slot(priority)
        async with semaphore:
            await _discogs_rate_limiter.acquire()
            response = await self._client.get(
                f"{DISCOGS_API_BASE}{path}", params=params
            )
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise RateLimitedError(
                "Discogs rate limit exceeded.",
                retry_after_seconds=_retry_after(response),
            )
        if response.status_code >= 500:
            raise _DiscogsTransientError("Discogs is temporarily unavailable.")
        if response.status_code != 200:
            raise DiscogsApiError("Discogs rejected the request.")
        try:
            return msgspec.json.decode(response.content, type=decode_type)
        except (msgspec.DecodeError, msgspec.ValidationError, TypeError) as error:
            raise DiscogsApiError("Discogs returned invalid release data.") from error

    async def get_release(
        self, release_id: str, *, priority: RequestPriority
    ) -> DiscogsRelease | None:
        key = discogs_release_key(release_id)
        cached = await self._cache.get(key)
        if isinstance(cached, DiscogsRelease):
            return cached

        async def load() -> DiscogsRelease | None:
            wire = await self._request(
                f"/releases/{release_id}",
                params=None,
                priority=priority,
                decode_type=DiscogsWireRelease,
            )
            if wire is None:
                return None
            normalized = normalize_release(wire, fetched_at=time.time())
            await self._cache.set(key, normalized, ttl_seconds=DISCOGS_CACHE_SECONDS)
            return normalized

        try:
            return await _discogs_deduplicator.dedupe(key, load)
        except RateLimitedError:
            raise
        except (DiscogsApiError, CircuitOpenError, httpx.HTTPError) as error:
            _record_degradation(type(error).__name__)
            return None

    async def search_releases(
        self,
        query: str,
        *,
        priority: RequestPriority,
        limit: int,
    ) -> list[DiscogsReleaseCandidate]:
        bounded_limit = max(1, min(limit, 10))
        normalized_query = " ".join(query.split())[:200]
        key = discogs_search_key(normalized_query, bounded_limit)
        cached = await self._cache.get(key)
        if isinstance(cached, list) and all(
            isinstance(item, DiscogsReleaseCandidate) for item in cached
        ):
            return cached

        async def load() -> list[DiscogsReleaseCandidate]:
            wire = await self._request(
                "/database/search",
                params={
                    "type": "release",
                    "q": normalized_query,
                    "per_page": str(bounded_limit),
                },
                priority=priority,
                decode_type=DiscogsWireSearchResponse,
            )
            if wire is None:
                return []
            fetched_at = time.time()
            candidates: list[DiscogsReleaseCandidate] = []
            for item in wire.results[:bounded_limit]:
                if item.id <= 0 or not item.title:
                    continue
                artist_name, separator, title = item.title.partition(" - ")
                formats = item.format or [fmt.name for fmt in item.formats if fmt.name]
                candidates.append(
                    DiscogsReleaseCandidate(
                        release_id=str(item.id),
                        master_id=str(item.master_id) if item.master_id else None,
                        title=title if separator else item.title,
                        artist_name=artist_name if separator else "",
                        canonical_url=f"{DISCOGS_WEB_BASE}/release/{item.id}",
                        year=item.year,
                        country=item.country or None,
                        label=item.label[0] if item.label else None,
                        catalogue_number=item.catno or None,
                        format_summary=", ".join(formats) or None,
                        fetched_at=fetched_at,
                    )
                )
            await self._cache.set(key, candidates, ttl_seconds=DISCOGS_CACHE_SECONDS)
            return candidates

        try:
            return await _discogs_deduplicator.dedupe(key, load)
        except RateLimitedError:
            raise
        except (DiscogsApiError, CircuitOpenError, httpx.HTTPError) as error:
            _record_degradation(type(error).__name__)
            return []
