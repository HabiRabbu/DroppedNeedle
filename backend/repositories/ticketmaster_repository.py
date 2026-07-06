"""Ticketmaster Discovery v2 client (Upcoming Events feature).

Actionable-failure repository: non-2xx and decode failures raise
``TicketmasterApiError`` (handler-mapped to 503), HTTP 429 raises
``RateLimitedError`` with the server's retry hint; raw httpx errors never
escape. Live behavior notes: ``repositories/TICKETMASTER_API_NOTES.md``.
"""

import logging

import httpx
import msgspec

from core.exceptions import RateLimitedError, TicketmasterApiError
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter
from infrastructure.resilience.retry import CircuitBreaker, with_retry
from repositories.ticketmaster_models import (
    TmAttraction,
    TmAttractionsResponse,
    TmEvent,
    TmEventsResponse,
)

logger = logging.getLogger(__name__)

TICKETMASTER_API_URL = "https://app.ticketmaster.com/discovery/v2"

# TM's docs state 5 req/s in one place and 2 req/s in another (verified
# 2026-07-06, see TICKETMASTER_API_NOTES.md) - encode the documented floor.
# The 5,000/day quota is enforced by sweep sizing, not this limiter.
_ticketmaster_rate_limiter = TokenBucketRateLimiter(rate=2.0)

_ticketmaster_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="ticketmaster",
)

_PAGE_SIZE = 200
_MAX_PAGES = 3  # 600 events per attraction covers the largest tours


def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


class TicketmasterRepository:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str) -> None:
        self._client = http_client
        self._api_key = api_key

    @with_retry(
        max_attempts=3,
        base_delay=0.5,
        max_delay=5.0,
        circuit_breaker=_ticketmaster_circuit_breaker,
        retriable_exceptions=(httpx.HTTPError, RateLimitedError),
    )
    async def _get(self, path: str, params: dict) -> bytes:
        await _ticketmaster_rate_limiter.acquire()
        response = await self._client.get(
            f"{TICKETMASTER_API_URL}{path}",
            params={**params, "apikey": self._api_key},
        )
        if response.status_code == 429:
            raise RateLimitedError(
                "Ticketmaster rate limit exceeded",
                retry_after_seconds=_parse_retry_after(response),
            )
        if response.status_code != 200:
            raise TicketmasterApiError(
                f"Ticketmaster returned HTTP {response.status_code}"
            )
        return response.content

    async def search_attractions(self, keyword: str) -> list[TmAttraction]:
        """Music attractions matching ``keyword``; [] means TM knows no such act."""
        content = await self._fetch(
            "/attractions.json",
            {"keyword": keyword, "classificationName": "Music", "size": "50"},
        )
        decoded = self._decode(content, TmAttractionsResponse)
        return decoded.embedded.attractions if decoded.embedded else []

    async def events_for_attraction(self, attraction_id: str) -> list[TmEvent]:
        """All upcoming events for one attraction, worldwide, oldest first.

        Follows pagination up to ``_MAX_PAGES``; a deeper result set is
        truncated with a warning (no silent caps).
        """
        events: list[TmEvent] = []
        for page_number in range(_MAX_PAGES):
            content = await self._fetch(
                "/events.json",
                {
                    "attractionId": attraction_id,
                    "sort": "date,asc",
                    "size": str(_PAGE_SIZE),
                    "page": str(page_number),
                },
            )
            decoded = self._decode(content, TmEventsResponse)
            events.extend(decoded.embedded.events if decoded.embedded else [])
            total_pages = decoded.page.total_pages if decoded.page else 1
            if page_number + 1 >= total_pages:
                return events
        logger.warning(
            "Ticketmaster events for attraction %s truncated at %d pages (%d events)",
            attraction_id,
            _MAX_PAGES,
            len(events),
        )
        return events

    async def test_connection(self) -> bool:
        """True iff the configured key can reach the Discovery API."""
        try:
            await self._fetch("/attractions.json", {"keyword": "test", "size": "1"})
        except (TicketmasterApiError, RateLimitedError):
            return False
        return True

    async def _fetch(self, path: str, params: dict) -> bytes:
        try:
            return await self._get(path, params)
        except (TicketmasterApiError, RateLimitedError):
            raise
        except httpx.HTTPError as exc:
            raise TicketmasterApiError(f"Ticketmaster request failed: {type(exc).__name__}") from exc

    @staticmethod
    def _decode(content: bytes, decode_type: type):
        try:
            return msgspec.json.decode(content, type=decode_type)
        except msgspec.MsgspecError as exc:
            raise TicketmasterApiError(f"Ticketmaster response decode failed: {exc}") from exc
