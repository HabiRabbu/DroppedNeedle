"""Ticketmaster Discovery v2 wire models.

Shapes verified against the live API on 2026-07-06 (see
``repositories/TICKETMASTER_API_NOTES.md``); decode fixtures live in
``tests/fixtures/events/``. Everything is tolerant-by-default: attractions
without ``externalLinks``, venues without ``location``, events without
``_embedded`` must all decode cleanly.
"""

import msgspec


class TmExternalId(msgspec.Struct, rename="camel"):
    id: str | None = None


class TmAttraction(msgspec.Struct, rename="camel"):
    id: str
    name: str = ""
    # dynamic key/value map; the key we consume is 'musicbrainz'
    external_links: dict[str, list[TmExternalId]] | None = None

    def musicbrainz_ids(self) -> list[str]:
        links = (self.external_links or {}).get("musicbrainz") or []
        return [link.id.strip().lower() for link in links if link.id and link.id.strip()]


class TmAttractionsEmbedded(msgspec.Struct, rename="camel"):
    attractions: list[TmAttraction] = []


class TmAttractionsResponse(msgspec.Struct, rename="camel"):
    # TM omits _embedded entirely when there are zero results
    embedded: TmAttractionsEmbedded | None = msgspec.field(name="_embedded", default=None)


class TmDateStart(msgspec.Struct, rename="camel"):
    local_date: str | None = None
    date_time: str | None = None


class TmDateStatus(msgspec.Struct, rename="camel"):
    code: str | None = None


class TmDates(msgspec.Struct, rename="camel"):
    start: TmDateStart | None = None
    status: TmDateStatus | None = None


class TmNamed(msgspec.Struct, rename="camel"):
    name: str | None = None


class TmVenueCountry(msgspec.Struct, rename="camel"):
    country_code: str | None = None


class TmLocation(msgspec.Struct, rename="camel"):
    # the wire carries coordinates as STRINGS ("51.46368200")
    latitude: str | None = None
    longitude: str | None = None


class TmVenue(msgspec.Struct, rename="camel"):
    name: str | None = None
    city: TmNamed | None = None
    state: TmNamed | None = None
    country: TmVenueCountry | None = None
    location: TmLocation | None = None


class TmEventEmbedded(msgspec.Struct, rename="camel"):
    venues: list[TmVenue] = []
    attractions: list[TmAttraction] = []


class TmEvent(msgspec.Struct, rename="camel"):
    id: str
    name: str = ""
    url: str | None = None
    dates: TmDates | None = None
    embedded: TmEventEmbedded | None = msgspec.field(name="_embedded", default=None)


class TmPage(msgspec.Struct, rename="camel"):
    size: int = 0
    total_elements: int = 0
    total_pages: int = 0
    number: int = 0


class TmEventsEmbedded(msgspec.Struct, rename="camel"):
    events: list[TmEvent] = []


class TmEventsResponse(msgspec.Struct, rename="camel"):
    embedded: TmEventsEmbedded | None = msgspec.field(name="_embedded", default=None)
    page: TmPage | None = None
