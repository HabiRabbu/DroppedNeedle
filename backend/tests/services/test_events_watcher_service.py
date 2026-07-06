"""EventsWatcherService tests.

Table-driven resolution tests (MBID pick / conflicting-MBID veto / "DJ Set"
sibling rejection / exact-name / tribute rejection / duplicate Skiddle ids),
mapping (statuses, coords, empty-string absences), cross-source dedupe (venue
name + coords paths), and sweep behavior against a REAL EventsStore: resolution
caching + 7-day TTL, stale-row deletion, supersede-delete, disabled-source row
retention, error cursors, and the badge-only SSE fan-out."""

import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.exceptions import TicketmasterApiError
from infrastructure.persistence.events_store import EventsStore
from infrastructure.persistence.follow_store import DistinctFollowedArtist
from models.events import LiveEventInput
from repositories.skiddle_models import SkiddleArtist, SkiddleEvent, SkiddleVenue
from repositories.ticketmaster_models import (
    TmAttraction,
    TmDates,
    TmDateStart,
    TmDateStatus,
    TmEvent,
    TmEventEmbedded,
    TmExternalId,
    TmLocation,
    TmNamed,
    TmVenue,
    TmVenueCountry,
)
from services.native.events_watcher_service import (
    RESOLUTION_TTL_SECONDS,
    EventsWatcherService,
    dedupe_across_sources,
    map_skiddle_event,
    map_tm_event,
    normalize_name,
    pick_skiddle_ids,
    pick_tm_attraction,
)

MBID = "fd87acc7-e0a0-4a45-bc2a-d2ab5c10be68"
ARTIST = DistinctFollowedArtist(
    artist_mbid=MBID.upper(), artist_mbid_lower=MBID, artist_name="Fontaines D.C."
)


def _attraction(id: str, name: str, mbids: list[str] | None = None) -> TmAttraction:
    links = {"musicbrainz": [TmExternalId(id=m) for m in mbids]} if mbids else None
    return TmAttraction(id=id, name=name, external_links=links)


def _tm_event(
    event_id: str = "tm-1",
    local_date: str | None = "2026-08-28",
    status: str = "onsale",
    venue_name: str = "Little John's Farm",
    lat: str | None = "51.456062",
    lon: str | None = "-0.991697",
) -> TmEvent:
    return TmEvent(
        id=event_id,
        name="Reading Festival",
        url="https://www.ticketmaster.co.uk/x",
        dates=TmDates(
            start=TmDateStart(local_date=local_date, date_time="2026-08-28T08:30:00Z"),
            status=TmDateStatus(code=status),
        ),
        embedded=TmEventEmbedded(
            venues=[
                TmVenue(
                    name=venue_name,
                    city=TmNamed(name="Reading"),
                    country=TmVenueCountry(country_code="GB"),
                    location=TmLocation(latitude=lat, longitude=lon),
                )
            ]
        ),
    )


def _sk_event(
    event_id: str = "sk-1",
    date: str | None = "2026-08-28",
    cancelled: str = "0",
    venue_name: str = "Little Johns Farm",
    lat: float | None = 51.4561,
    lon: float | None = -0.9917,
    ticket_url: str = "",
) -> SkiddleEvent:
    return SkiddleEvent(
        id=event_id,
        eventname="Reading Festival",
        date=date,
        startdate="2026-08-28T11:00:00+00:00",
        cancelled=cancelled,
        link="https://www.skiddle.com/festivals/Reading/",
        ticket_url=ticket_url,
        venue=SkiddleVenue(
            name=venue_name, town="Reading", country="GB", latitude=lat, longitude=lon
        ),
    )


# -- pure matching helpers -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fontaines D.C.", "fontainesdc"),
        ("Fontaines DC", "fontainesdc"),
        ("Fontaines CD", "fontainescd"),
        ("  CHVRCHES  ", "chvrches"),
        ("", ""),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_pick_tm_attraction_prefers_mbid_match():
    attractions = [
        _attraction("A-dj", "Fontaines D.C. DJ Set"),
        _attraction("A-real", "Fontaines D.C.", [MBID]),
    ]
    assert pick_tm_attraction(attractions, "Fontaines D.C.", MBID) == ("A-real", "mbid")


def test_pick_tm_attraction_rejects_dj_set_sibling():
    # phrase-contains the artist name but is not name-equal -> no match
    attractions = [_attraction("A-dj", "Fontaines D.C. DJ Set")]
    assert pick_tm_attraction(attractions, "Fontaines D.C.", MBID) == (None, "none")


def test_pick_tm_attraction_conflicting_mbid_vetoes_name_match():
    attractions = [_attraction("A-fake", "Fontaines D.C.", ["some-other-mbid"])]
    assert pick_tm_attraction(attractions, "Fontaines D.C.", MBID) == (None, "none")


def test_pick_tm_attraction_exact_name_without_mbids():
    attractions = [_attraction("A-1", "Fontaines DC")]  # punctuation-insensitive
    assert pick_tm_attraction(attractions, "Fontaines D.C.", MBID) == ("A-1", "exact_name")


def test_pick_skiddle_ids_collects_duplicates_and_rejects_tribute():
    artists = [
        SkiddleArtist(id="1", name="Fontaines CD"),  # tribute near-name
        SkiddleArtist(id="2", name="Fontaines D.C."),
        SkiddleArtist(id="3", name="Fontaines DC"),  # Skiddle duplicate entry
    ]
    assert pick_skiddle_ids(artists, "Fontaines D.C.") == ["2", "3"]


# -- mapping --------------------------------------------------------------------


def test_map_tm_event_full_row():
    row = map_tm_event(_tm_event(), ARTIST, "mbid")
    assert row.source == "ticketmaster"
    assert row.local_date == "2026-08-28"
    assert row.status == "scheduled"  # onsale normalizes to scheduled
    assert row.match_confidence == "mbid"
    assert row.city == "Reading"
    assert row.country_code == "GB"
    assert row.latitude == pytest.approx(51.456062)  # string coords parsed
    assert row.ticket_url == "https://www.ticketmaster.co.uk/x"


def test_map_tm_event_dateless_is_dropped_and_statuses_map():
    assert map_tm_event(_tm_event(local_date=None), ARTIST, "mbid") is None
    row = map_tm_event(_tm_event(status="cancelled"), ARTIST, "name")
    assert row.status == "cancelled"
    assert row.match_confidence == "name"
    # a postponed gig isn't happening on its listed date; nearest badge
    assert map_tm_event(_tm_event(status="postponed"), ARTIST, "mbid").status == "rescheduled"


def test_map_skiddle_event_quirks():
    row = map_skiddle_event(_sk_event(), ARTIST)
    assert row.source == "skiddle"
    assert row.status == "scheduled"
    assert row.match_confidence == "name"
    assert row.ticket_url == "https://www.skiddle.com/festivals/Reading/"  # '' -> link
    assert map_skiddle_event(_sk_event(cancelled="1"), ARTIST).status == "cancelled"
    assert map_skiddle_event(_sk_event(date=None), ARTIST) is None


# -- cross-source dedupe ---------------------------------------------------------


def _row(source: str, event_id: str, **overrides) -> LiveEventInput:
    fields = {
        "source": source,
        "source_event_id": event_id,
        "artist_mbid_lower": MBID,
        "artist_name": ARTIST.artist_name,
        "event_name": "Reading Festival",
        "local_date": "2026-08-28",
        "status": "scheduled",
        "match_confidence": "mbid" if source == "ticketmaster" else "name",
        "venue_name": "Little John's Farm",
        "latitude": 51.456,
        "longitude": -0.9917,
    }
    fields.update(overrides)
    return LiveEventInput(**fields)


def test_dedupe_drops_skiddle_duplicate_by_venue_name():
    kept = dedupe_across_sources(
        [
            _row("ticketmaster", "tm-1"),
            _row("skiddle", "sk-1", venue_name="little johns farm", latitude=None,
                 longitude=None),
        ]
    )
    assert [(r.source, r.source_event_id) for r in kept] == [("ticketmaster", "tm-1")]


def test_dedupe_drops_skiddle_duplicate_by_proximity():
    kept = dedupe_across_sources(
        [
            _row("ticketmaster", "tm-1", venue_name="Reading Fest Site"),
            _row("skiddle", "sk-1", venue_name="Little Johns", latitude=51.457,
                 longitude=-0.992),
        ]
    )
    assert len(kept) == 1
    assert kept[0].source == "ticketmaster"


def test_dedupe_keeps_distinct_gigs():
    kept = dedupe_across_sources(
        [
            _row("ticketmaster", "tm-1"),
            _row("skiddle", "sk-1", local_date="2026-08-29"),  # different day
            _row("skiddle", "sk-2", venue_name="The Jacaranda", latitude=53.4024,
                 longitude=-2.9796),  # different venue, far away
        ]
    )
    assert len(kept) == 3


# -- sweep behavior (real store, stubbed repos) ----------------------------------


class _Prefs:
    def __init__(
        self,
        tm: bool = True,
        skiddle: bool = True,
        ready: bool = True,
        scope: str = "followed",
    ):
        self._tm, self._skiddle, self._ready, self._scope = tm, skiddle, ready, scope

    def is_events_source_ready(self) -> bool:
        return self._ready

    def get_events_settings_raw(self):
        from api.v1.schemas.settings import EventsSettings

        return EventsSettings(
            enabled=True,
            ticketmaster_enabled=self._tm,
            ticketmaster_api_key="tm-key" if self._tm else "",
            skiddle_enabled=self._skiddle,
            skiddle_api_key="sk-key" if self._skiddle else "",
            sweep_scope=self._scope,
        )


class _Clock:
    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _service(store, tm=None, skiddle=None, prefs=None, follows=None, sse=None, clock=None):
    follows = follows or AsyncMock()
    tm = tm or AsyncMock()
    skiddle = skiddle or AsyncMock()
    sse = sse or AsyncMock()
    return (
        EventsWatcherService(
            events_store=store,
            follow_store=follows,
            ticketmaster_repo=tm,
            skiddle_repo=skiddle,
            preferences=prefs or _Prefs(),
            sse_publisher=sse,
            inter_artist_delay=0,
            now_fn=clock or _Clock(),
        ),
        tm,
        skiddle,
        follows,
        sse,
    )


@pytest.fixture
def store(tmp_path: Path) -> EventsStore:
    return EventsStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())


def _follows_with(artists: list[DistinctFollowedArtist], followers: list[str]) -> AsyncMock:
    follows = AsyncMock()
    follows.list_distinct_followed_artists.return_value = artists
    follows.list_followers.return_value = followers
    return follows


@pytest.mark.asyncio
async def test_sweep_skips_when_not_ready(store):
    service, tm, _, follows, _ = _service(store, prefs=_Prefs(ready=False))
    summary = await service.run_sweep()
    assert summary.skipped is True
    follows.list_distinct_followed_artists.assert_not_awaited()
    tm.search_attractions.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_sweep_resolves_fetches_upserts_and_notifies(store):
    follows = _follows_with([ARTIST], ["user-a", "user-b"])
    tm, skiddle, sse = AsyncMock(), AsyncMock(), AsyncMock()
    tm.search_attractions.return_value = [
        _attraction("A-dj", "Fontaines D.C. DJ Set"),
        _attraction("A-real", "Fontaines D.C.", [MBID]),
    ]
    tm.events_for_attraction.return_value = [_tm_event()]
    skiddle.search_artists.return_value = [
        SkiddleArtist(id="2", name="Fontaines D.C."),
        SkiddleArtist(id="3", name="Fontaines DC"),
    ]
    # duplicate ids return the same event + one that dupes the TM row
    skiddle.events_for_artist.return_value = [
        _sk_event("sk-dupe"),  # same gig as tm-1 -> dropped by dedupe
        _sk_event("sk-club", venue_name="The Jacaranda", lat=53.4024, lon=-2.9796),
    ]
    service, *_ = _service(store, tm=tm, skiddle=skiddle, follows=follows, sse=sse)

    summary = await service.run_sweep()

    assert summary.artists_swept == 1
    assert summary.errors == 0
    events = await store.list_events_for_artist(MBID)
    by_key = {(e.source, e.source_event_id): e for e in events}
    assert set(by_key) == {("ticketmaster", "tm-1"), ("skiddle", "sk-club")}
    assert by_key[("ticketmaster", "tm-1")].match_confidence == "mbid"
    assert by_key[("skiddle", "sk-club")].match_confidence == "name"
    # resolutions cached
    assert (await store.get_tm_resolution(MBID)).attraction_id == "A-real"
    assert (await store.get_skiddle_resolution(MBID)).artist_ids == ["2", "3"]
    # each of Skiddle's duplicate ids was queried once
    assert skiddle.events_for_artist.await_count == 2
    # badge-only SSE fan-out to every follower
    assert sse.publish.await_count == 2
    channel, event_name, payload = sse.publish.await_args_list[0].args
    assert channel == "user:user-a"
    assert event_name == "concerts_new"
    assert payload["new_events"] == 2


@pytest.mark.asyncio
async def test_resolution_cached_within_ttl_and_rerun_after_expiry(store):
    clock = _Clock()
    follows = _follows_with([ARTIST], [])
    tm = AsyncMock()
    tm.search_attractions.return_value = [_attraction("A-real", "Fontaines D.C.", [MBID])]
    tm.events_for_attraction.return_value = [_tm_event()]
    service, *_ = _service(
        store, tm=tm, follows=follows, prefs=_Prefs(skiddle=False), clock=clock
    )

    await service.run_sweep()
    await service.run_sweep()
    assert tm.search_attractions.await_count == 1  # cached within the TTL

    clock.now += RESOLUTION_TTL_SECONDS + 1
    await service.run_sweep()
    assert tm.search_attractions.await_count == 2  # TTL expiry re-resolves


@pytest.mark.asyncio
async def test_negative_resolution_is_cached_too(store):
    follows = _follows_with([ARTIST], [])
    tm = AsyncMock()
    tm.search_attractions.return_value = []  # no TM presence
    service, *_ = _service(store, tm=tm, follows=follows, prefs=_Prefs(skiddle=False))

    await service.run_sweep()
    await service.run_sweep()

    assert tm.search_attractions.await_count == 1  # negative result cached
    tm.events_for_attraction.assert_not_awaited()
    assert (await store.get_tm_resolution(MBID)).match_basis == "none"


@pytest.mark.asyncio
async def test_stale_rows_deleted_and_supersede(store):
    follows = _follows_with([ARTIST], [])
    tm, skiddle = AsyncMock(), AsyncMock()
    # sweep 1: skiddle only sees the gig
    tm.search_attractions.return_value = []
    skiddle.search_artists.return_value = [SkiddleArtist(id="2", name="Fontaines D.C.")]
    skiddle.events_for_artist.return_value = [_sk_event("sk-1")]
    service, *_ = _service(store, tm=tm, skiddle=skiddle, follows=follows)
    await service.run_sweep()
    assert {(e.source, e.source_event_id) for e in await store.list_events_for_artist(MBID)} == {
        ("skiddle", "sk-1")
    }

    # sweep 2 (post-TTL not needed - fresh service, same store): TM now lists the
    # same gig -> the Skiddle row loses the dedupe and is superseded
    clock = _Clock(now=1_000.0 + RESOLUTION_TTL_SECONDS + 1)
    tm2, skiddle2 = AsyncMock(), AsyncMock()
    tm2.search_attractions.return_value = [_attraction("A-real", "Fontaines D.C.", [MBID])]
    tm2.events_for_attraction.return_value = [_tm_event("tm-1")]
    skiddle2.search_artists.return_value = [SkiddleArtist(id="2", name="Fontaines D.C.")]
    skiddle2.events_for_artist.return_value = [_sk_event("sk-1")]
    service2, *_ = _service(store, tm=tm2, skiddle=skiddle2, follows=follows, clock=clock)
    await service2.run_sweep()

    assert {(e.source, e.source_event_id) for e in await store.list_events_for_artist(MBID)} == {
        ("ticketmaster", "tm-1")
    }


@pytest.mark.asyncio
async def test_disabled_source_keeps_its_rows(store):
    follows = _follows_with([ARTIST], [])
    tm, skiddle = AsyncMock(), AsyncMock()
    tm.search_attractions.return_value = []
    skiddle.search_artists.return_value = [SkiddleArtist(id="2", name="Fontaines D.C.")]
    skiddle.events_for_artist.return_value = [
        _sk_event("sk-club", venue_name="The Jacaranda", lat=53.4, lon=-2.98)
    ]
    service, *_ = _service(store, tm=tm, skiddle=skiddle, follows=follows)
    await service.run_sweep()

    # skiddle now disabled: its stored rows must survive the next sweep
    tm2 = AsyncMock()
    tm2.search_attractions.return_value = []
    service2, *_ = _service(store, tm=tm2, follows=follows, prefs=_Prefs(skiddle=False))
    await service2.run_sweep()

    assert [(e.source, e.source_event_id) for e in await store.list_events_for_artist(MBID)] == [
        ("skiddle", "sk-club")
    ]


@pytest.mark.asyncio
async def test_library_scope_unions_and_dedupes_library_artists(store):
    import sqlite3

    conn = sqlite3.connect(store.db_path)
    conn.executescript(
        f"""
        CREATE TABLE library_artists (
            mbid_lower TEXT PRIMARY KEY, mbid TEXT NOT NULL, name TEXT NOT NULL,
            album_count INTEGER DEFAULT 0, date_added INTEGER, raw_json TEXT NOT NULL
        );
        INSERT INTO library_artists VALUES ('{MBID}', '{MBID}', 'Fontaines D.C.', 1, 1, '{{}}');
        INSERT INTO library_artists VALUES ('mbid-lib', 'mbid-lib', 'Crawlers', 1, 1, '{{}}');
        """
    )
    conn.commit()
    conn.close()

    follows = _follows_with([ARTIST], [])
    tm = AsyncMock()
    tm.search_attractions.return_value = []
    service, *_ = _service(
        store, tm=tm, follows=follows, prefs=_Prefs(skiddle=False, scope="library")
    )
    summary = await service.run_sweep()

    # followed artist deduped against its library row; the extra library
    # artist joins the sweep
    assert summary.artists_swept == 2
    searched = {call.args[0] for call in tm.search_attractions.await_args_list}
    assert searched == {"Fontaines D.C.", "Crawlers"}


@pytest.mark.asyncio
async def test_sweep_cap_rotates_least_recently_checked_first(store, monkeypatch, caplog):
    from services.native import events_watcher_service as module

    monkeypatch.setattr(module, "MAX_ARTISTS_PER_SWEEP", 1)
    fresh = DistinctFollowedArtist(
        artist_mbid="MB-FRESH", artist_mbid_lower="mb-fresh", artist_name="Fresh"
    )
    await store.update_cursor("mb-fresh", "ok")  # recently checked -> sorts last
    follows = _follows_with([fresh, ARTIST], [])
    tm = AsyncMock()
    tm.search_attractions.return_value = []
    service, *_ = _service(store, tm=tm, follows=follows, prefs=_Prefs(skiddle=False))

    with caplog.at_level("WARNING"):
        summary = await service.run_sweep()

    assert summary.artists_swept == 1
    tm.search_attractions.assert_awaited_once_with(ARTIST.artist_name)  # never-checked first
    assert any("per-sweep budget" in r.message for r in caplog.records)

    # next sweep: the just-checked artist now sorts last -> the other one runs
    tm2 = AsyncMock()
    tm2.search_attractions.return_value = []
    service2, *_ = _service(store, tm=tm2, follows=follows, prefs=_Prefs(skiddle=False))
    await service2.run_sweep()
    tm2.search_attractions.assert_awaited_once_with("Fresh")


@pytest.mark.asyncio
async def test_catchup_skip_drops_recently_checked_artists(store):
    """A restart's catch-up sweep must not re-spend quota on artists already
    swept today; scheduled sweeps (skip=None) still cover everyone."""
    clock = _Clock(now=100_000.0)
    fresh = DistinctFollowedArtist(
        artist_mbid="MB-FRESH", artist_mbid_lower="mb-fresh", artist_name="Fresh"
    )
    await store.update_cursor("mb-fresh", "ok")  # checked "now" (real time.time)
    import time as _time

    clock.now = _time.time()  # align the service clock with the cursor stamp
    follows = _follows_with([fresh, ARTIST], [])
    tm = AsyncMock()
    tm.search_attractions.return_value = []
    service, *_ = _service(store, tm=tm, follows=follows, prefs=_Prefs(skiddle=False), clock=clock)

    summary = await service.run_sweep(skip_recent_hours=20)
    assert summary.artists_swept == 1  # only the never-checked artist
    tm.search_attractions.assert_awaited_once_with(ARTIST.artist_name)

    summary = await service.run_sweep()  # scheduled sweep: no skip
    assert summary.artists_swept == 2


@pytest.mark.asyncio
async def test_provider_error_records_cursor_and_continues(store):
    other = DistinctFollowedArtist(
        artist_mbid="MB-2", artist_mbid_lower="mb-2", artist_name="Loathe"
    )
    follows = _follows_with([ARTIST, other], [])
    tm = AsyncMock()
    tm.search_attractions.side_effect = [
        TicketmasterApiError("boom"),
        [_attraction("A-2", "Loathe", ["mb-2"])],
    ]
    tm.events_for_attraction.return_value = []
    service, *_ = _service(store, tm=tm, follows=follows, prefs=_Prefs(skiddle=False))

    summary = await service.run_sweep()

    assert summary.errors == 1
    assert summary.artists_swept == 2
    assert tm.search_attractions.await_count == 2  # second artist still swept

    def read_cursors(conn):
        rows = conn.execute(
            "SELECT artist_mbid_lower, last_status FROM artist_event_check"
        ).fetchall()
        return {row["artist_mbid_lower"]: row["last_status"] for row in rows}

    cursors = await store._read(read_cursors)
    assert cursors[MBID] == "error"
    assert cursors["mb-2"] == "ok"


@pytest.mark.asyncio
async def test_prune_runs_each_sweep(store):
    await store.apply_sweep_result(MBID, [
        LiveEventInput(
            source="ticketmaster", source_event_id="old", artist_mbid_lower=MBID,
            artist_name="x", event_name="x", local_date="2000-01-01",
            status="scheduled", match_confidence="mbid",
        )
    ])
    follows = _follows_with([], [])
    service, *_ = _service(store, follows=follows)
    summary = await service.run_sweep()
    assert summary.events_removed == 1
    assert await store.list_events_for_artist(MBID) == []
