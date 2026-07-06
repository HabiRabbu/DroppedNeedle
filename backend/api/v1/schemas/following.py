from typing import Annotated

import msgspec

from infrastructure.msgspec_fastapi import AppStruct


class FollowedArtistResponse(AppStruct):
    mbid: str
    name: str
    auto_download: bool
    auto_download_state: str
    followed_at: float
    image_url: str | None = None


class NewReleaseResponse(AppStruct):
    release_group_mbid: str
    title: str
    artist_name: str
    artist_mbid: str
    primary_type: str | None = None
    first_release_date: str | None = None
    in_library: bool = False  # meaningful on the recent-releases log view


class WantedResponse(AppStruct):
    items: list[NewReleaseResponse]
    total: int


class UnseenCountResponse(AppStruct):
    count: int


class ConcertResponse(AppStruct):
    artist_mbid: str
    artist_name: str
    event_name: str
    local_date: str
    status: str  # scheduled | cancelled | rescheduled
    source: str  # ticketmaster | skiddle
    source_event_id: str  # unique per source; the frontend's render key
    matched_city: str
    venue_name: str | None = None
    city: str | None = None
    region: str | None = None
    country_code: str | None = None
    starts_at: str | None = None
    ticket_url: str | None = None
    distance_km: float | None = None  # None when matched by city name only


class ConcertsResponse(AppStruct):
    configured: bool  # false = admin has no enabled events source
    items: list[ConcertResponse]
    total: int


class EventCityPayload(AppStruct):
    # out-of-range coordinates would poison every subsequent haversine call
    city_name: str
    latitude: Annotated[float, msgspec.Meta(ge=-90, le=90)]
    longitude: Annotated[float, msgspec.Meta(ge=-180, le=180)]
    radius_km: float = 30.0
    country_code: str | None = None


class EventCitiesResponse(AppStruct):
    items: list[EventCityPayload]


class EventCitiesUpdateRequest(AppStruct):
    items: list[EventCityPayload]


class CitySearchResult(AppStruct):
    name: str
    latitude: float
    longitude: float
    country_code: str | None = None
    country: str | None = None
    region: str | None = None


class CitySearchResponse(AppStruct):
    items: list[CitySearchResult]
