"""Skiddle API client (Upcoming Events feature, UK/IE depth source).

Actionable-failure repository: non-2xx, decode failures and Skiddle's own
``error != 0`` envelope raise ``SkiddleApiError`` (handler-mapped to 503);
HTTP 429 raises ``RateLimitedError``; raw httpx errors never escape. Live
behavior notes: ``repositories/SKIDDLE_API_NOTES.md``.
"""

import logging

import httpx
import msgspec

from core.exceptions import RateLimitedError, SkiddleApiError
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter
from infrastructure.resilience.retry import CircuitBreaker, with_retry
from repositories.skiddle_models import (
    SkiddleArtist,
    SkiddleArtistsResponse,
    SkiddleEvent,
    SkiddleEventsResponse,
)

logger = logging.getLogger(__name__)

SKIDDLE_API_URL = "https://www.skiddle.com/api/v1"

# Skiddle documents only that unspecified daily + hourly caps exist (verified
# 2026-07-06, see SKIDDLE_API_NOTES.md) - stay conservative at 1 req/s.
_skiddle_rate_limiter = TokenBucketRateLimiter(rate=1.0)

_skiddle_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="skiddle",
)


class SkiddleRepository:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str) -> None:
        self._client = http_client
        self._api_key = api_key

    @with_retry(
        max_attempts=3,
        base_delay=0.5,
        max_delay=5.0,
        circuit_breaker=_skiddle_circuit_breaker,
        retriable_exceptions=(httpx.HTTPError, RateLimitedError),
    )
    async def _get(self, path: str, params: dict) -> bytes:
        await _skiddle_rate_limiter.acquire()
        response = await self._client.get(
            f"{SKIDDLE_API_URL}{path}",
            params={**params, "api_key": self._api_key},
        )
        if response.status_code == 429:
            raise RateLimitedError("Skiddle rate limit exceeded")
        if response.status_code != 200:
            raise SkiddleApiError(f"Skiddle returned HTTP {response.status_code}")
        return response.content

    async def search_artists(self, name: str) -> list[SkiddleArtist]:
        """Artists matching ``name``; [] means Skiddle knows no such act."""
        content = await self._fetch("/artists/", {"name": name})
        decoded = self._decode(content, SkiddleArtistsResponse)
        if decoded.error != 0:
            raise SkiddleApiError(
                f"Skiddle artists search failed: {decoded.errormessage or decoded.error}"
            )
        return decoded.results

    async def events_for_artist(self, artist_id: str) -> list[SkiddleEvent]:
        """Upcoming events tagged with one Skiddle artistid (`a=` filter)."""
        content = await self._fetch(
            "/events/search/", {"a": artist_id, "description": "1"}
        )
        decoded = self._decode(content, SkiddleEventsResponse)
        if decoded.error != 0:
            raise SkiddleApiError(
                f"Skiddle events search failed: {decoded.errormessage or decoded.error}"
            )
        return decoded.results

    async def test_connection(self) -> bool:
        """True iff the configured key can reach the events API."""
        try:
            content = await self._fetch("/events/search/", {"limit": "1"})
            decoded = self._decode(content, SkiddleEventsResponse)
        except (SkiddleApiError, RateLimitedError):
            return False
        return decoded.error == 0

    async def _fetch(self, path: str, params: dict) -> bytes:
        try:
            return await self._get(path, params)
        except (SkiddleApiError, RateLimitedError):
            raise
        except httpx.HTTPError as exc:
            raise SkiddleApiError(f"Skiddle request failed: {type(exc).__name__}") from exc

    @staticmethod
    def _decode(content: bytes, decode_type: type):
        try:
            return msgspec.json.decode(content, type=decode_type)
        except msgspec.MsgspecError as exc:
            raise SkiddleApiError(f"Skiddle response decode failed: {exc}") from exc
