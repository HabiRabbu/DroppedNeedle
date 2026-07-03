"""30-second track/album previews via Deezer (primary) and iTunes (fallback).

Both APIs are keyless. Deezer matches better (field-scoped ``artist:"x" track:"y"``
query syntax and ordered album track lists); iTunes is the fallback and its top hit
can be a cover, so results are verified against the requested artist. Preview URLs
from Deezer expire (``hdnea`` token) - callers must treat them as short-lived.
"""

import logging
import re

import httpx
import msgspec

from core.exceptions import ExternalServiceError, RateLimitedError
from infrastructure.degradation import try_get_degradation_context
from infrastructure.integration_result import IntegrationResult
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter
from infrastructure.resilience.retry import CircuitBreaker, with_retry
from repositories.deezer_models import (
    DeezerAlbumSearchResponse,
    DeezerAlbumTracksResponse,
    DeezerTrackSearchResponse,
    ITunesSearchResponse,
    PreviewTrack,
)

logger = logging.getLogger(__name__)

_SOURCE = "preview"

DEEZER_API_URL = "https://api.deezer.com"
ITUNES_API_URL = "https://itunes.apple.com/search"


def _record_degradation(msg: str) -> None:
    ctx = try_get_degradation_context()
    if ctx is not None:
        ctx.record(IntegrationResult.error(source=_SOURCE, msg=msg))


_deezer_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="deezer",
)

_itunes_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="itunes",
)

# Deezer documents 50 requests / 5 s per IP -> stay well under at 5/s.
_deezer_rate_limiter = TokenBucketRateLimiter(rate=5.0, capacity=5)
# iTunes Search API is unofficially ~20 req/min -> 0.3/s keeps us safe.
_itunes_rate_limiter = TokenBucketRateLimiter(rate=0.3, capacity=2)


def _norm(value: str) -> str:
    """Loose comparison form: casefold and strip non-alphanumerics."""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _names_match(wanted: str, got: str) -> bool:
    if not wanted or not got:
        return False
    a, b = _norm(wanted), _norm(got)
    return bool(a) and (a in b or b in a)


class PreviewRepository:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @with_retry(
        max_attempts=2,
        base_delay=1.0,
        max_delay=5.0,
        circuit_breaker=_deezer_circuit_breaker,
        retriable_exceptions=(httpx.HTTPError, ExternalServiceError, RateLimitedError),
    )
    async def _deezer_get(self, path: str, params: dict[str, str]) -> bytes:
        await _deezer_rate_limiter.acquire()
        response = await self._client.get(f"{DEEZER_API_URL}{path}", params=params, timeout=10.0)
        if response.status_code == 429:
            raise RateLimitedError("Deezer rate limit exceeded", retry_after_seconds=5)
        if response.status_code >= 400:
            raise ExternalServiceError(f"Deezer returned HTTP {response.status_code}")
        return response.content

    @with_retry(
        max_attempts=2,
        base_delay=2.0,
        max_delay=8.0,
        circuit_breaker=_itunes_circuit_breaker,
        retriable_exceptions=(httpx.HTTPError, ExternalServiceError, RateLimitedError),
    )
    async def _itunes_get(self, params: dict[str, str]) -> bytes:
        await _itunes_rate_limiter.acquire()
        response = await self._client.get(ITUNES_API_URL, params=params, timeout=10.0)
        if response.status_code == 429:
            raise RateLimitedError("iTunes rate limit exceeded", retry_after_seconds=60)
        if response.status_code >= 400:
            raise ExternalServiceError(f"iTunes returned HTTP {response.status_code}")
        return response.content

    async def _deezer_track_preview(self, artist: str, track: str) -> PreviewTrack | None:
        raw = await self._deezer_get(
            "/search", {"q": f'artist:"{artist}" track:"{track}"', "limit": "3"}
        )
        try:
            decoded = msgspec.json.decode(raw, type=DeezerTrackSearchResponse)
        except msgspec.DecodeError as e:
            raise ExternalServiceError(f"Deezer track search decode failed: {e}")
        for hit in decoded.data:
            if hit.preview:
                return PreviewTrack(
                    title=hit.title_short or hit.title,
                    artist_name=hit.artist.name if hit.artist else artist,
                    preview_url=hit.preview,
                    duration_s=30,
                    position=hit.track_position,
                )
        return None

    async def _deezer_album_tracks(
        self, artist: str, album: str, limit: int
    ) -> list[PreviewTrack]:
        raw = await self._deezer_get(
            "/search/album", {"q": f'artist:"{artist}" album:"{album}"', "limit": "3"}
        )
        try:
            albums = msgspec.json.decode(raw, type=DeezerAlbumSearchResponse)
        except msgspec.DecodeError as e:
            raise ExternalServiceError(f"Deezer album search decode failed: {e}")

        album_id = None
        for hit in albums.data:
            hit_artist = hit.artist.name if hit.artist else ""
            if hit.id and _names_match(artist, hit_artist):
                album_id = hit.id
                break
        if album_id is None and albums.data and albums.data[0].id:
            # fall back to the top hit when the artist field is missing/odd
            album_id = albums.data[0].id
        if album_id is None:
            return []

        raw = await self._deezer_get(f"/album/{album_id}/tracks", {"limit": str(max(limit, 4))})
        try:
            tracks = msgspec.json.decode(raw, type=DeezerAlbumTracksResponse)
        except msgspec.DecodeError as e:
            raise ExternalServiceError(f"Deezer album tracks decode failed: {e}")

        results: list[PreviewTrack] = []
        for t in tracks.data:
            if not t.preview:
                continue
            results.append(
                PreviewTrack(
                    title=t.title_short or t.title,
                    artist_name=t.artist.name if t.artist else artist,
                    preview_url=t.preview,
                    duration_s=30,
                    position=t.track_position or (len(results) + 1),
                )
            )
            if len(results) >= limit:
                break
        return results

    async def _itunes_track_preview(self, artist: str, track: str) -> PreviewTrack | None:
        raw = await self._itunes_get(
            {"term": f"{artist} {track}", "entity": "song", "limit": "5"}
        )
        try:
            decoded = msgspec.json.decode(raw, type=ITunesSearchResponse)
        except msgspec.DecodeError as e:
            raise ExternalServiceError(f"iTunes search decode failed: {e}")
        for hit in decoded.results:
            # iTunes' top hit can be a cover version - verify the artist
            if hit.preview_url and _names_match(artist, hit.artist_name):
                return PreviewTrack(
                    title=hit.track_name,
                    artist_name=hit.artist_name,
                    preview_url=hit.preview_url,
                    duration_s=30,
                )
        return None

    async def _itunes_album_tracks(
        self, artist: str, album: str, limit: int
    ) -> list[PreviewTrack]:
        raw = await self._itunes_get(
            {"term": f"{artist} {album}", "entity": "song", "limit": "25"}
        )
        try:
            decoded = msgspec.json.decode(raw, type=ITunesSearchResponse)
        except msgspec.DecodeError as e:
            raise ExternalServiceError(f"iTunes album search decode failed: {e}")
        results: list[PreviewTrack] = []
        for hit in decoded.results:
            if not hit.preview_url:
                continue
            if not _names_match(artist, hit.artist_name):
                continue
            if not _names_match(album, hit.collection_name):
                continue
            results.append(
                PreviewTrack(
                    title=hit.track_name,
                    artist_name=hit.artist_name,
                    preview_url=hit.preview_url,
                    duration_s=30,
                    position=hit.track_number or (len(results) + 1),
                )
            )
            if len(results) >= limit:
                break
        results.sort(key=lambda t: t.position or 0)
        return results

    async def get_artist_top_tracks(self, artist: str, limit: int = 5) -> list[PreviewTrack]:
        """An artist's popular tracks via Deezer search (keyless). Used as the
        last-resort radio source when ListenBrainz's popularity API and Last.fm
        are unavailable; results also carry 30s preview URLs."""
        try:
            raw = await self._deezer_get(
                "/search", {"q": f'artist:"{artist}"', "limit": str(max(limit * 2, 10))}
            )
            decoded = msgspec.json.decode(raw, type=DeezerTrackSearchResponse)
        except Exception as e:  # noqa: BLE001 - optional source: absence, not failure
            logger.debug("Deezer artist top tracks failed for %s: %s", artist, e)
            return []
        results: list[PreviewTrack] = []
        seen: set[str] = set()
        for hit in decoded.data:
            hit_artist = hit.artist.name if hit.artist else ""
            if not _names_match(artist, hit_artist):
                continue
            title = hit.title_short or hit.title
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            results.append(
                PreviewTrack(
                    title=title,
                    artist_name=hit_artist or artist,
                    preview_url=hit.preview,
                    duration_s=30,
                )
            )
            if len(results) >= limit:
                break
        return results

    async def get_track_preview(
        self, artist: str, track: str
    ) -> tuple[PreviewTrack | None, str | None]:
        """A single 30s preview; returns (track, provider) with Deezer→iTunes fallback."""
        try:
            found = await self._deezer_track_preview(artist, track)
            if found:
                return found, "deezer"
        except Exception as e:  # noqa: BLE001 - optional enrichment: fall through to iTunes
            logger.debug("Deezer track preview failed for %s - %s: %s", artist, track, e)
        try:
            found = await self._itunes_track_preview(artist, track)
            if found:
                return found, "itunes"
        except Exception as e:  # noqa: BLE001 - optional enrichment: absence, not failure
            _record_degradation(f"track preview lookup failed: {e}")
            logger.debug("iTunes track preview failed for %s - %s: %s", artist, track, e)
        return None, None

    async def get_album_preview_tracks(
        self, artist: str, album: str, limit: int = 4
    ) -> tuple[list[PreviewTrack], str | None]:
        """Ordered 30s samples of an album's first tracks, Deezer→iTunes fallback."""
        try:
            tracks = await self._deezer_album_tracks(artist, album, limit)
            if tracks:
                return tracks, "deezer"
        except Exception as e:  # noqa: BLE001 - optional enrichment: fall through to iTunes
            logger.debug("Deezer album preview failed for %s - %s: %s", artist, album, e)
        try:
            tracks = await self._itunes_album_tracks(artist, album, limit)
            if tracks:
                return tracks, "itunes"
        except Exception as e:  # noqa: BLE001 - optional enrichment: absence, not failure
            _record_degradation(f"album preview lookup failed: {e}")
            logger.debug("iTunes album preview failed for %s - %s: %s", artist, album, e)
        return [], None
