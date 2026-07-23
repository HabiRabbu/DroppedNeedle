"""Typed, cache-aside LRCLIB reads for optional Library Management lyrics."""

import hashlib

import httpx
import msgspec

from core.exceptions import LrclibApiError, RateLimitedError
from infrastructure.cache.cache_keys import lrclib_exact_lyrics_key
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.degradation import try_get_degradation_context
from infrastructure.http.deduplication import RequestDeduplicator
from infrastructure.integration_result import IntegrationResult
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter
from infrastructure.resilience.retry import CircuitBreaker, with_retry
from models.library_management_enrichment import LyricsCandidate, LyricsLookupResult
from repositories.lrclib_models import LrclibLyricsResponse

LRCLIB_API_URL = "https://lrclib.net"
_SOURCE = "lrclib"
_POSITIVE_TTL_SECONDS = 7 * 24 * 60 * 60
_NEGATIVE_TTL_SECONDS = 6 * 60 * 60
_MAX_LYRICS_BYTES = 2 * 1024 * 1024
_MAX_LYRICS_CHARACTERS = 1_000_000

# LRCLIB publishes no numeric request allowance. This conservative client-side ceiling
# is intentionally below ordinary interactive use and is not a claim about its limit.
_lrclib_rate_limiter = TokenBucketRateLimiter(rate=1.0, capacity=2)
_lrclib_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="lrclib",
)
_lrclib_deduplicator = RequestDeduplicator()


def _record_degradation(message: str) -> None:
    context = try_get_degradation_context()
    if context is not None:
        context.record(IntegrationResult.error(source=_SOURCE, msg=message))


def _retry_after(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    if value is not None:
        try:
            seconds = float(value)
            if seconds > 0:
                return min(seconds, 30.0)
        except ValueError:
            pass
    return 2.0


class LrclibRepository:
    def __init__(self, http_client: httpx.AsyncClient, cache: CacheInterface) -> None:
        self._client = http_client
        self._cache = cache
        self._base_url = LRCLIB_API_URL

    @with_retry(
        max_attempts=3,
        base_delay=1.0,
        max_delay=3.0,
        circuit_breaker=_lrclib_breaker,
        retriable_exceptions=(LrclibApiError,),
        non_breaking_exceptions=(RateLimitedError,),
    )
    async def _request_exact(
        self,
        *,
        track_name: str,
        artist_name: str,
        album_name: str,
        duration_seconds: int,
    ) -> LyricsLookupResult:
        await _lrclib_rate_limiter.acquire()
        try:
            response = await self._client.get(
                f"{self._base_url}/api/get",
                params={
                    "track_name": track_name,
                    "artist_name": artist_name,
                    "album_name": album_name,
                    "duration": duration_seconds,
                },
            )
        except httpx.HTTPError as error:
            _record_degradation("LRCLIB could not be reached.")
            raise LrclibApiError("LRCLIB request failed.") from error
        if response.status_code == 404:
            return LyricsLookupResult(found=False)
        if response.status_code == 429:
            _record_degradation("LRCLIB rate limited the lyrics lookup.")
            raise RateLimitedError(
                "LRCLIB rate limited the lyrics lookup.",
                retry_after_seconds=_retry_after(response),
            )
        if response.status_code != 200:
            _record_degradation("LRCLIB returned an unsuccessful response.")
            raise LrclibApiError(
                f"LRCLIB lookup failed with HTTP {response.status_code}."
            )
        if len(response.content) > _MAX_LYRICS_BYTES:
            _record_degradation("LRCLIB returned an oversized lyrics response.")
            raise LrclibApiError("LRCLIB returned an oversized lyrics response.")
        try:
            raw = msgspec.json.decode(response.content, type=LrclibLyricsResponse)
        except msgspec.DecodeError as error:
            _record_degradation("LRCLIB returned an invalid lyrics response.")
            raise LrclibApiError(
                "LRCLIB returned an invalid lyrics response."
            ) from error
        if (
            raw.id <= 0
            or not raw.track_name.strip()
            or not raw.artist_name.strip()
            or not raw.album_name.strip()
            or raw.duration <= 0
        ):
            _record_degradation("LRCLIB returned an incomplete lyrics response.")
            raise LrclibApiError("LRCLIB returned an incomplete lyrics response.")
        plain = raw.plain_lyrics.strip() if raw.plain_lyrics else None
        synced = raw.synced_lyrics.strip() if raw.synced_lyrics else None
        if any(
            lyrics is not None and len(lyrics) > _MAX_LYRICS_CHARACTERS
            for lyrics in (plain, synced)
        ):
            _record_degradation("LRCLIB returned oversized lyrics content.")
            raise LrclibApiError("LRCLIB returned oversized lyrics content.")
        if not plain and not synced and not raw.instrumental:
            return LyricsLookupResult(found=False)
        revision = hashlib.sha256(response.content).hexdigest()
        return LyricsLookupResult(
            found=True,
            candidate=LyricsCandidate(
                provider_id=raw.id,
                track_name=raw.track_name.strip(),
                artist_name=raw.artist_name.strip(),
                album_name=raw.album_name.strip(),
                duration_seconds=raw.duration,
                instrumental=raw.instrumental,
                plain_lyrics=plain,
                synced_lyrics=synced,
                provider_revision=revision,
            ),
        )

    async def get_exact_lyrics(
        self,
        *,
        track_name: str,
        artist_name: str,
        album_name: str,
        duration_seconds: int,
    ) -> LyricsLookupResult:
        key = lrclib_exact_lyrics_key(
            track_name, artist_name, album_name, duration_seconds
        )
        cached = await self._cache.get(key)
        if isinstance(cached, LyricsLookupResult):
            return cached

        async def fetch() -> LyricsLookupResult:
            result = await self._request_exact(
                track_name=track_name,
                artist_name=artist_name,
                album_name=album_name,
                duration_seconds=duration_seconds,
            )
            await self._cache.set(
                key,
                result,
                ttl_seconds=(
                    _POSITIVE_TTL_SECONDS if result.found else _NEGATIVE_TTL_SECONDS
                ),
            )
            return result

        return await _lrclib_deduplicator.dedupe(key, fetch)
