"""Skiddle API wire models.

Shapes verified against the live API on 2026-07-06 (see
``repositories/SKIDDLE_API_NOTES.md``); decode fixtures live in
``tests/fixtures/events/``. Wire quirks to preserve: ``cancelled`` is the
STRING ``'0'``/``'1'``, ids are strings, venue coordinates are floats, empty
strings stand in for absent values (``ticketUrl``, ``cancellationDate``),
and key casing is mixed (``eventname`` vs ``ticketUrl`` vs ``EventCode``).
"""

import msgspec


class SkiddleArtist(msgspec.Struct):
    id: str
    name: str = ""
    spotifyartisturl: str | None = None


class SkiddleArtistsResponse(msgspec.Struct):
    error: int = 0
    errormessage: str | None = None
    # int on the artists endpoint but a STRING on events ("392") - keep both
    # tolerant since we never consume it
    totalcount: int | str = 0
    results: list[SkiddleArtist] = []


class SkiddleVenue(msgspec.Struct):
    name: str | None = None
    town: str | None = None
    region: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class SkiddleEventArtist(msgspec.Struct):
    artistid: str | None = None
    name: str | None = None


class SkiddleEvent(msgspec.Struct):
    id: str
    eventname: str = ""
    date: str | None = None  # venue-local YYYY-MM-DD
    startdate: str | None = None  # ISO datetime
    cancelled: str | None = None  # '0' / '1' on the wire
    rescheduled_date: str | None = msgspec.field(name="rescheduledDate", default=None)
    link: str | None = None
    ticket_url: str | None = msgspec.field(name="ticketUrl", default=None)
    venue: SkiddleVenue | None = None
    artists: list[SkiddleEventArtist] = []

    def is_cancelled(self) -> bool:
        return self.cancelled == "1"

    def is_rescheduled(self) -> bool:
        return bool((self.rescheduled_date or "").strip())


class SkiddleEventsResponse(msgspec.Struct):
    error: int = 0
    errormessage: str | None = None
    totalcount: int | str = 0
    results: list[SkiddleEvent] = []
