"""Open-Meteo geocoding client (the events city picker).

A city search is a USER-INITIATED action, not optional enrichment: failures
raise ``GeocodingApiError`` (handler-mapped to 503) so the UI can show
"geocoding unavailable" - a silent ``[]`` would read as "no such city" (R1).

Live-verified 2026-07-06: ``geocoding-api.open-meteo.com/v1/search?name=…``
needs no API key; ``?name=Liverpool`` returns Liverpool GB first with float
coordinates, ``country_code``, and ``admin1`` region.
"""

import httpx
import msgspec

from core.exceptions import GeocodingApiError, RateLimitedError
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter
from infrastructure.resilience.retry import CircuitBreaker, with_retry

GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Open-Meteo's documented free non-commercial limits (verified 2026-07-06):
# 600/min, 5,000/h, 10,000/day. A debounced search box sits far below 2/s.
_geocoding_rate_limiter = TokenBucketRateLimiter(rate=2.0)

_geocoding_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="open-meteo-geocoding",
)


class GeoCity(msgspec.Struct):
    name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    country_code: str | None = None
    country: str | None = None
    admin1: str | None = None


class _GeocodingResponse(msgspec.Struct):
    results: list[GeoCity] = []


class GeocodingRepository:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @with_retry(
        max_attempts=3,
        base_delay=0.5,
        max_delay=3.0,
        circuit_breaker=_geocoding_circuit_breaker,
        retriable_exceptions=(httpx.HTTPError, RateLimitedError),
    )
    async def _get(self, params: dict) -> bytes:
        await _geocoding_rate_limiter.acquire()
        response = await self._client.get(GEOCODING_API_URL, params=params)
        if response.status_code == 429:
            raise RateLimitedError("Geocoding rate limit exceeded")
        if response.status_code != 200:
            raise GeocodingApiError(f"Geocoding returned HTTP {response.status_code}")
        return response.content

    async def search_cities(self, query: str, count: int = 8) -> list[GeoCity]:
        """Cities matching ``query``; [] means the geocoder knows no such place
        (a provider failure raises instead)."""
        try:
            content = await self._get(
                {"name": query, "count": str(count), "language": "en", "format": "json"}
            )
        except (GeocodingApiError, RateLimitedError):
            raise
        except httpx.HTTPError as exc:
            raise GeocodingApiError(
                f"Geocoding request failed: {type(exc).__name__}"
            ) from exc
        try:
            decoded = msgspec.json.decode(content, type=_GeocodingResponse)
        except msgspec.MsgspecError as exc:
            raise GeocodingApiError(f"Geocoding response decode failed: {exc}") from exc
        return decoded.results
