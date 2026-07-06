"""Upcoming Events watcher (.dev-notes/Events, D1-D4 + R1).

One global sweep over the DISTINCT followed artists. Per artist and per
enabled source: resolve the source's artist entity (cached with a 7-day TTL,
negative results included), fetch its upcoming events, normalize, dedupe
across sources (Ticketmaster's MBID-confirmed rows win), diff against the
stored feed and apply upserts + stale deletes in one transaction, then notify
followers over SSE (badge-only ``concerts_new``).

Matching happens at RESOLUTION time, never per event (20-API-PROBES.md):
- TM: prefer the attraction whose externalLinks carry our MBID; else an
  exact-ish name match with no conflicting MBID. Phrase containment is never
  enough ("Fontaines D.C. DJ Set").
- Skiddle: exact-ish name equality only ("Fontaines CD" tribute trap),
  collecting ALL matching ids (Skiddle keeps duplicates per act).

A per-artist failure is logged and recorded on that artist's cursor without
being retried until the next sweep; the run never raises.
"""

import asyncio
import logging
import math
import re
from datetime import date, timedelta

import httpx
import msgspec

from core.exceptions import ExternalServiceError
from infrastructure.persistence.events_store import EventsStore
from infrastructure.persistence.follow_store import FollowStore
from infrastructure.resilience.retry import CircuitOpenError
from models.events import LiveEventInput, SweepArtist
from repositories.protocols.skiddle import SkiddleRepositoryProtocol
from repositories.protocols.ticketmaster import TicketmasterRepositoryProtocol
from repositories.skiddle_models import SkiddleEvent
from repositories.ticketmaster_models import TmAttraction, TmEvent

logger = logging.getLogger(__name__)

RESOLUTION_TTL_SECONDS = 7 * 86400
_PRUNE_GRACE_DAYS = 2
# far-future noise guard; deliberately a constant, not a setting (R1)
_HORIZON_DAYS = 365
_DEDUPE_KM = 1.0
_FETCH_TIMEOUT = 60.0
# TM's free quota is 5,000 calls/day; steady state costs ~1.14 calls per
# artist per day (1 events call + 1/7 amortized re-resolution), so ~4,300
# artists saturate it. Cap each sweep and rotate least-recently-checked-first,
# so a bigger set (library scope) gets full coverage across successive days.
MAX_ARTISTS_PER_SWEEP = 3500

_TM_STATUS_MAP = {
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "rescheduled": "rescheduled",
    # a postponed gig isn't happening on its listed date - closest badge we have
    "postponed": "rescheduled",
}

_ALNUM_RE = re.compile(r"[^a-z0-9]+")


class SweepSummary(msgspec.Struct, frozen=True):
    artists_swept: int = 0
    events_upserted: int = 0
    events_removed: int = 0
    errors: int = 0
    skipped: bool = False


def normalize_name(name: str) -> str:
    """Exact-ish name key: lowercase alphanumerics only, so 'Fontaines D.C.'
    == 'Fontaines DC' but != 'Fontaines CD'."""
    return _ALNUM_RE.sub("", (name or "").lower())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    # float error can push a past 1 for near-antipodal pairs; asin would raise
    return 2 * radius * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def pick_tm_attraction(
    attractions: list[TmAttraction], artist_name: str, artist_mbid_lower: str
) -> tuple[str | None, str]:
    """Resolve the TM attraction for an artist -> (attraction_id, match_basis).

    1. Any attraction carrying our MBID wins outright ('mbid').
    2. Else an exact-ish name match with NO MBIDs at all ('exact_name') - a
       name-equal attraction with a conflicting MBID is vetoed.
    3. Else no TM presence ('none').
    """
    for attraction in attractions:
        if artist_mbid_lower in attraction.musicbrainz_ids():
            return attraction.id, "mbid"
    target = normalize_name(artist_name)
    if target:
        for attraction in attractions:
            if normalize_name(attraction.name) != target:
                continue
            if attraction.musicbrainz_ids():
                continue  # conflicting MBID vetoes, whatever the name says
            return attraction.id, "exact_name"
    return None, "none"


def pick_skiddle_ids(artists, artist_name: str) -> list[str]:
    """ALL Skiddle ids whose name matches exact-ish (duplicates are real)."""
    target = normalize_name(artist_name)
    if not target:
        return []
    return [a.id for a in artists if normalize_name(a.name) == target]


def _parse_coord(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def map_tm_event(
    event: TmEvent, artist: SweepArtist, match_confidence: str
) -> LiveEventInput | None:
    start = event.dates.start if event.dates else None
    local_date = start.local_date if start else None
    if not local_date:
        return None  # dateless events (TBA) are unusable for a city/date feed
    status_code = ((event.dates.status.code if event.dates.status else None) or "").lower()
    venue = (event.embedded.venues if event.embedded else None) or []
    first_venue = venue[0] if venue else None
    location = first_venue.location if first_venue else None
    return LiveEventInput(
        source="ticketmaster",
        source_event_id=event.id,
        artist_mbid_lower=artist.artist_mbid_lower,
        artist_name=artist.artist_name,
        event_name=event.name or "",
        local_date=local_date,
        status=_TM_STATUS_MAP.get(status_code, "scheduled"),
        match_confidence=match_confidence,
        venue_name=first_venue.name if first_venue else None,
        city=first_venue.city.name if first_venue and first_venue.city else None,
        region=first_venue.state.name if first_venue and first_venue.state else None,
        country_code=(
            first_venue.country.country_code if first_venue and first_venue.country else None
        ),
        latitude=_parse_coord(location.latitude) if location else None,
        longitude=_parse_coord(location.longitude) if location else None,
        starts_at=start.date_time if start else None,
        ticket_url=event.url,
    )


def map_skiddle_event(
    event: SkiddleEvent, artist: SweepArtist
) -> LiveEventInput | None:
    if not event.date:
        return None
    if event.is_cancelled():
        status = "cancelled"
    elif event.is_rescheduled():
        status = "rescheduled"
    else:
        status = "scheduled"
    venue = event.venue
    return LiveEventInput(
        source="skiddle",
        source_event_id=event.id,
        artist_mbid_lower=artist.artist_mbid_lower,
        artist_name=artist.artist_name,
        event_name=event.eventname or "",
        local_date=event.date,
        status=status,
        match_confidence="name",  # Skiddle has no MBIDs on the wire
        venue_name=venue.name if venue else None,
        city=venue.town if venue else None,
        region=venue.region if venue else None,
        country_code=venue.country if venue else None,
        latitude=venue.latitude if venue else None,
        longitude=venue.longitude if venue else None,
        starts_at=event.startdate,
        ticket_url=(event.ticket_url or "").strip() or event.link,
    )


def _same_gig(a: LiveEventInput, b: LiveEventInput) -> bool:
    """R1 dedupe rule: same local date AND (fold-normalized venue names match
    OR venue coordinates within ~1 km)."""
    if a.local_date != b.local_date:
        return False
    name_a, name_b = normalize_name(a.venue_name or ""), normalize_name(b.venue_name or "")
    if name_a and name_a == name_b:
        return True
    if (
        a.latitude is not None
        and a.longitude is not None
        and b.latitude is not None
        and b.longitude is not None
    ):
        return haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) <= _DEDUPE_KM
    return False


def dedupe_across_sources(events: list[LiveEventInput]) -> list[LiveEventInput]:
    """Drop Skiddle rows that duplicate a Ticketmaster row (TM wins: its
    matching is MBID-grade and its rows are richer)."""
    tm_rows = [e for e in events if e.source == "ticketmaster"]
    kept = list(tm_rows)
    for row in events:
        if row.source == "ticketmaster":
            continue
        if any(_same_gig(row, tm) for tm in tm_rows):
            continue
        kept.append(row)
    return kept


class EventsWatcherService:
    def __init__(
        self,
        events_store: EventsStore,
        follow_store: FollowStore,
        ticketmaster_repo: TicketmasterRepositoryProtocol,
        skiddle_repo: SkiddleRepositoryProtocol,
        preferences,
        sse_publisher,
        inter_artist_delay: float = 1.0,
        now_fn=None,
    ) -> None:
        self._store = events_store
        self._follows = follow_store
        self._tm = ticketmaster_repo
        self._skiddle = skiddle_repo
        self._preferences = preferences
        self._sse = sse_publisher
        self._inter_artist_delay = inter_artist_delay
        import time as _time

        self._now = now_fn or _time.time

    async def run_sweep(self, skip_recent_hours: float | None = None) -> SweepSummary:
        """``skip_recent_hours`` drops artists whose cursor is fresher than the
        window - the startup catch-up passes ~20h so a restart doesn't re-spend
        the day's API quota on artists already swept (this host restarts on
        every deploy). Scheduled and settings-kicked sweeps pass None."""
        if not self._preferences.is_events_source_ready():
            logger.debug("Events sweep skipped: no enabled source with a key")
            return SweepSummary(skipped=True)
        raw = self._preferences.get_events_settings_raw()
        tm_on = raw.ticketmaster_enabled and bool(raw.ticketmaster_api_key)
        skiddle_on = raw.skiddle_enabled and bool(raw.skiddle_api_key)

        removed = await self._store.prune_past_events(
            (date.today() - timedelta(days=_PRUNE_GRACE_DAYS)).isoformat()
        )
        artists = await self._sweep_artists(raw.sweep_scope, skip_recent_hours)
        upserted = errors = 0
        for index, artist in enumerate(artists):
            try:
                upserted += await self._process_artist(artist, tm_on, skiddle_on)
            except (
                CircuitOpenError,
                ExternalServiceError,
                httpx.HTTPError,
                asyncio.TimeoutError,
            ) as exc:
                await self._store.update_cursor(artist.artist_mbid_lower, "error", str(exc))
                logger.warning(
                    "Events sweep: source unavailable for %s: %s",
                    artist.artist_mbid_lower,
                    exc,
                )
                errors += 1
            except Exception as exc:  # noqa: BLE001 - one artist must never kill the run
                logger.error(
                    "Events sweep: unexpected error for %s: %s",
                    artist.artist_mbid_lower,
                    exc,
                    exc_info=True,
                )
                errors += 1
            if index < len(artists) - 1 and self._inter_artist_delay > 0:
                await asyncio.sleep(self._inter_artist_delay)

        summary = SweepSummary(
            artists_swept=len(artists),
            events_upserted=upserted,
            events_removed=removed,
            errors=errors,
        )
        logger.info("Events sweep complete: %s", summary)
        return summary

    async def _sweep_artists(
        self, scope: str, skip_recent_hours: float | None = None
    ) -> list[SweepArtist]:
        """The sweep set for the configured scope, least-recently-checked first
        and capped at MAX_ARTISTS_PER_SWEEP (capped artists rotate into the
        next sweep because the swept ones get fresh cursor timestamps)."""
        followed = await self._follows.list_distinct_followed_artists()
        by_mbid = {
            f.artist_mbid_lower: SweepArtist(
                artist_mbid=f.artist_mbid,
                artist_mbid_lower=f.artist_mbid_lower,
                artist_name=f.artist_name,
            )
            for f in followed
        }
        if scope == "library":
            for artist in await self._store.list_library_artists():
                by_mbid.setdefault(artist.artist_mbid_lower, artist)
        ages = await self._store.cursor_ages()
        artists = sorted(
            by_mbid.values(), key=lambda a: ages.get(a.artist_mbid_lower, 0.0)
        )
        if skip_recent_hours is not None:
            fresh_after = self._now() - skip_recent_hours * 3600
            artists = [
                a for a in artists if ages.get(a.artist_mbid_lower, 0.0) < fresh_after
            ]
        if len(artists) > MAX_ARTISTS_PER_SWEEP:
            logger.warning(
                "Events sweep: %d artists exceed the per-sweep budget of %d;"
                " sweeping the least-recently-checked, the rest rotate into"
                " the next sweep",
                len(artists),
                MAX_ARTISTS_PER_SWEEP,
            )
            artists = artists[:MAX_ARTISTS_PER_SWEEP]
        return artists

    async def _process_artist(
        self, artist: SweepArtist, tm_on: bool, skiddle_on: bool
    ) -> int:
        collected: list[LiveEventInput] = []
        if tm_on:
            collected.extend(await asyncio.wait_for(
                self._fetch_ticketmaster(artist), timeout=_FETCH_TIMEOUT
            ))
        if skiddle_on:
            collected.extend(await asyncio.wait_for(
                self._fetch_skiddle(artist), timeout=_FETCH_TIMEOUT
            ))

        horizon = (date.today() + timedelta(days=_HORIZON_DAYS)).isoformat()
        collected = [e for e in collected if e.local_date <= horizon]
        collected = dedupe_across_sources(collected)

        existing = await self._store.list_events_for_artist(artist.artist_mbid_lower)
        existing_keys = {(e.source, e.source_event_id) for e in existing}
        collected_keys = {(e.source, e.source_event_id) for e in collected}
        # remove rows that vanished upstream or lost the dedupe - but only for
        # sources actually swept this run (a disabled source keeps its rows)
        swept_sources = ({"ticketmaster"} if tm_on else set()) | (
            {"skiddle"} if skiddle_on else set()
        )
        delete_keys = [
            key
            for key in existing_keys - collected_keys
            if key[0] in swept_sources
        ]
        await self._store.apply_sweep_result(
            artist.artist_mbid_lower, collected, delete_keys, now=self._now()
        )
        await self._store.update_cursor(artist.artist_mbid_lower, "ok")

        new_count = len(collected_keys - existing_keys)
        if new_count:
            await self._publish_new_events(artist, new_count)
        return new_count

    async def _fetch_ticketmaster(self, artist: SweepArtist) -> list[LiveEventInput]:
        resolution = await self._store.get_tm_resolution(artist.artist_mbid_lower)
        if resolution is None or self._now() - resolution.resolved_at > RESOLUTION_TTL_SECONDS:
            attractions = await self._tm.search_attractions(artist.artist_name)
            attraction_id, basis = pick_tm_attraction(
                attractions, artist.artist_name, artist.artist_mbid_lower
            )
            await self._store.set_tm_resolution(
                artist.artist_mbid_lower, attraction_id, basis, now=self._now()
            )
        else:
            attraction_id, basis = resolution.attraction_id, resolution.match_basis
        if not attraction_id:
            return []
        confidence = "mbid" if basis == "mbid" else "name"
        events = await self._tm.events_for_attraction(attraction_id)
        mapped = (map_tm_event(e, artist, confidence) for e in events)
        return [m for m in mapped if m is not None]

    async def _fetch_skiddle(self, artist: SweepArtist) -> list[LiveEventInput]:
        resolution = await self._store.get_skiddle_resolution(artist.artist_mbid_lower)
        if resolution is None or self._now() - resolution.resolved_at > RESOLUTION_TTL_SECONDS:
            artists = await self._skiddle.search_artists(artist.artist_name)
            ids = pick_skiddle_ids(artists, artist.artist_name)
            await self._store.set_skiddle_resolution(
                artist.artist_mbid_lower, ids, now=self._now()
            )
        else:
            ids = resolution.artist_ids
        collected: dict[str, LiveEventInput] = {}
        for skiddle_id in ids:
            for event in await self._skiddle.events_for_artist(skiddle_id):
                mapped = map_skiddle_event(event, artist)
                if mapped is not None:
                    # duplicate artistids return the same events - last wins
                    collected[mapped.source_event_id] = mapped
        return list(collected.values())

    async def _publish_new_events(
        self, artist: SweepArtist, new_count: int
    ) -> None:
        try:
            followers = await self._follows.list_followers(artist.artist_mbid_lower)
            for user_id in followers:
                await self._sse.publish(
                    f"user:{user_id}",
                    "concerts_new",
                    {
                        "artist_mbid": artist.artist_mbid,
                        "artist_name": artist.artist_name,
                        "new_events": new_count,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - notification is best-effort
            logger.debug("Events sweep: SSE publish failed: %s", exc)
