"""Upcoming Events read side (.dev-notes/Events).

Serves the per-user concerts view: feed rows joined to the user's follows
(store-side) filtered against the user's saved cities (here, via haversine -
one user's candidate rows number in the hundreds at most). Events without
venue coordinates fall back to case-insensitive city-name equality. A user
with no saved cities sees an empty list (the UI walks them into adding one).
"""

import logging
from datetime import date

import msgspec

from infrastructure.persistence.events_store import EventsStore
from models.events import EventCity, LiveEvent, UserConcert
from services.native.events_watcher_service import haversine_km

logger = logging.getLogger(__name__)

MAX_CITIES = 50
MIN_RADIUS_KM = 1.0
MAX_RADIUS_KM = 500.0


class MatchedConcert(msgspec.Struct, frozen=True):
    event: LiveEvent
    artist_mbid: str
    matched_city: str
    distance_km: float | None  # None when matched by city name (no coords)


def _match_city(event: LiveEvent, city: EventCity) -> float | None:
    """Distance in km when the event falls inside the city's radius, the
    sentinel -1.0 for a coordinate-less name match, or None for no match."""
    if event.latitude is not None and event.longitude is not None:
        distance = haversine_km(city.latitude, city.longitude, event.latitude, event.longitude)
        return distance if distance <= city.radius_km else None
    if event.city and event.city.strip().lower() == city.city_name.strip().lower():
        return -1.0
    return None


def filter_to_cities(
    concerts: list[UserConcert], cities: list[EventCity]
) -> list[MatchedConcert]:
    matched: list[MatchedConcert] = []
    for concert in concerts:
        best: tuple[float, EventCity] | None = None
        for city in cities:
            distance = _match_city(concert.event, city)
            if distance is None:
                continue
            if best is None or distance < best[0]:
                best = (distance, city)
        if best is not None:
            distance, city = best
            matched.append(
                MatchedConcert(
                    event=concert.event,
                    artist_mbid=concert.artist_mbid,
                    matched_city=city.city_name,
                    distance_km=None if distance < 0 else round(distance, 1),
                )
            )
    return matched


class EventsService:
    def __init__(self, events_store: EventsStore, preferences) -> None:
        self._store = events_store
        self._preferences = preferences

    def is_configured(self) -> bool:
        return self._preferences.is_events_source_ready()

    async def _candidate_concerts(
        self, user_id: str, discovered_after: float | None = None
    ):
        """Feed rows in scope for this user: their follows, or - in library
        sweep scope - the whole feed (the shared library's events belong to
        everyone; per-user cities still narrow them)."""
        min_date = date.today().isoformat()
        scope = self._preferences.get_events_settings_raw().sweep_scope
        if scope == "library":
            return await self._store.list_all_events(
                min_local_date=min_date, discovered_after=discovered_after
            )
        return await self._store.list_events_for_user(
            user_id, min_local_date=min_date, discovered_after=discovered_after
        )

    async def list_concerts(self, user_id: str) -> list[MatchedConcert]:
        cities = await self._store.list_cities(user_id)
        if not cities:
            return []
        return filter_to_cities(await self._candidate_concerts(user_id), cities)

    async def count_unseen(self, user_id: str) -> int:
        cities = await self._store.list_cities(user_id)
        if not cities:
            return 0
        seen_at = await self._store.get_seen_at(user_id)
        concerts = await self._candidate_concerts(user_id, discovered_after=seen_at)
        return len(filter_to_cities(concerts, cities))

    async def mark_seen(self, user_id: str) -> None:
        await self._store.mark_seen(user_id)

    async def list_cities(self, user_id: str) -> list[EventCity]:
        return await self._store.list_cities(user_id)

    async def replace_cities(self, user_id: str, cities: list[EventCity]) -> list[EventCity]:
        clamped = [
            msgspec.structs.replace(
                city, radius_km=min(MAX_RADIUS_KM, max(MIN_RADIUS_KM, city.radius_km))
            )
            for city in cities[:MAX_CITIES]
        ]
        await self._store.replace_cities(user_id, clamped)
        return await self._store.list_cities(user_id)
