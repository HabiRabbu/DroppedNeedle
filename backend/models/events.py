"""Upcoming Events domain models (Events plan, .dev-notes/Events).

A ``LiveEvent`` is one (event, matched artist) pair in the shared global feed:
multi-artist bills (festivals) produce one row per followed co-headliner, so
the same source event can legitimately appear under several artist MBIDs.
"""

import msgspec

# normalized event status (TM dates.status.code + Skiddle cancelled/rescheduled
# fields both map onto these three)
EVENT_STATUSES = ("scheduled", "cancelled", "rescheduled")

# how the artist was matched to the source's entity (resolution basis):
# 'mbid' = TM attraction carried our MusicBrainz id; 'name' = exact-name match
MATCH_CONFIDENCES = ("mbid", "name")


class SweepArtist(msgspec.Struct, frozen=True):
    """One artist the watcher sweeps - from the follow store, the library
    artist index, or both (library scope unions them)."""

    artist_mbid: str
    artist_mbid_lower: str
    artist_name: str


class LiveEventInput(msgspec.Struct, frozen=True):
    """One feed row as produced by a watcher sweep (timestamps are stamped by
    the store: ``discovered_at`` on first insert only, ``updated_at`` always)."""

    source: str  # 'ticketmaster' | 'skiddle'
    source_event_id: str
    artist_mbid_lower: str
    artist_name: str
    event_name: str
    local_date: str  # venue-local YYYY-MM-DD
    status: str  # EVENT_STATUSES
    match_confidence: str  # MATCH_CONFIDENCES
    venue_name: str | None = None
    city: str | None = None
    region: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    starts_at: str | None = None  # ISO datetime when the source provides one
    ticket_url: str | None = None


class LiveEvent(msgspec.Struct, frozen=True):
    """A stored feed row (read model)."""

    source: str
    source_event_id: str
    artist_mbid_lower: str
    artist_name: str
    event_name: str
    local_date: str
    status: str
    match_confidence: str
    discovered_at: float
    updated_at: float
    venue_name: str | None = None
    city: str | None = None
    region: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    starts_at: str | None = None
    ticket_url: str | None = None


class UserConcert(msgspec.Struct, frozen=True):
    """A feed row joined to one user's follow (carries the original-case MBID
    from the follow row for artist-page links)."""

    event: LiveEvent
    artist_mbid: str


class EventCity(msgspec.Struct, frozen=True):
    """One entry in a user's city picker."""

    city_name: str
    latitude: float
    longitude: float
    radius_km: float
    position: int
    country_code: str | None = None


class TmResolution(msgspec.Struct, frozen=True):
    """Cached Ticketmaster attraction resolution for one artist.

    ``attraction_id`` is None iff ``match_basis == 'none'`` (no TM presence);
    negative results still carry ``resolved_at`` so the re-resolution TTL works.
    """

    attraction_id: str | None
    match_basis: str  # 'mbid' | 'exact_name' | 'none'
    resolved_at: float


class SkiddleResolution(msgspec.Struct, frozen=True):
    """Cached Skiddle artistid resolution for one artist (1-to-many: Skiddle
    keeps duplicate entries per real act). Empty ``artist_ids`` = no presence."""

    artist_ids: list[str]
    resolved_at: float
