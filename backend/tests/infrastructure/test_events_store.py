"""EventsStore tests - construct-twice idempotency, sweep-diff upsert semantics
(discovered_at preserved, deletes in the same transaction), per-user feed join
+ date/discovered filters, prune, cursor upsert, TM/Skiddle resolution caches
(incl. negative results), city replace-all, seen marker, and the auth_users
ON DELETE CASCADE."""

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from infrastructure.persistence.events_store import EventsStore
from models.events import EventCity, LiveEventInput


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "library.db"
    conn = sqlite3.connect(path)
    # prerequisite tables seeded raw (never via other stores)
    conn.executescript(
        """
        CREATE TABLE auth_users (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        );
        CREATE TABLE user_followed_artists (
            user_id TEXT NOT NULL,
            artist_mbid TEXT NOT NULL,
            artist_mbid_lower TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            auto_download INTEGER NOT NULL DEFAULT 0,
            followed_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, artist_mbid_lower)
        );
        """
    )
    conn.execute(
        "INSERT INTO auth_users (id, display_name, created_at) VALUES ('user-a', 'A', '2026')"
    )
    conn.execute(
        "INSERT INTO auth_users (id, display_name, created_at) VALUES ('user-b', 'B', '2026')"
    )
    conn.execute(
        "INSERT INTO user_followed_artists VALUES ('user-a', 'MBID-1', 'mbid-1', 'Fontaines D.C.', 0, 1, 1)"
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def store(db_path: Path) -> EventsStore:
    return EventsStore(db_path=db_path, write_lock=threading.Lock())


def _event(event_id: str = "tm-1", **overrides) -> LiveEventInput:
    fields = {
        "source": "ticketmaster",
        "source_event_id": event_id,
        "artist_mbid_lower": "mbid-1",
        "artist_name": "Fontaines D.C.",
        "event_name": "Reading Festival",
        "local_date": "2026-08-28",
        "status": "scheduled",
        "match_confidence": "mbid",
        "venue_name": "Little John's Farm",
        "city": "Reading",
        "country_code": "GB",
        "latitude": 51.4637,
        "longitude": -0.9849,
        "ticket_url": "https://www.ticketmaster.co.uk/x",
    }
    fields.update(overrides)
    return LiveEventInput(**fields)


def test_construct_twice_is_idempotent(db_path: Path):
    lock = threading.Lock()
    EventsStore(db_path=db_path, write_lock=lock)
    EventsStore(db_path=db_path, write_lock=lock)  # re-run must not error
    assert db_path.exists()


@pytest.mark.asyncio
async def test_upsert_roundtrip(store: EventsStore):
    await store.apply_sweep_result("mbid-1", [_event()])
    events = await store.list_events_for_artist("mbid-1")
    assert len(events) == 1
    ev = events[0]
    assert ev.source_event_id == "tm-1"
    assert ev.event_name == "Reading Festival"
    assert ev.status == "scheduled"
    assert ev.match_confidence == "mbid"
    assert ev.latitude == pytest.approx(51.4637)
    assert ev.discovered_at > 0


@pytest.mark.asyncio
async def test_upsert_preserves_discovered_at_and_bumps_updated_at(store: EventsStore):
    await store.apply_sweep_result("mbid-1", [_event()], now=100.0)
    await store.apply_sweep_result(
        "mbid-1", [_event(status="cancelled")], now=200.0
    )
    events = await store.list_events_for_artist("mbid-1")
    assert len(events) == 1
    assert events[0].discovered_at == 100.0  # first sight stands
    assert events[0].updated_at == 200.0
    assert events[0].status == "cancelled"


@pytest.mark.asyncio
async def test_sweep_deletes_superseded_rows_in_same_call(store: EventsStore):
    await store.apply_sweep_result("mbid-1", [_event("sk-9", source="skiddle")])
    await store.apply_sweep_result(
        "mbid-1", [_event("tm-1")], delete_keys=[("skiddle", "sk-9")]
    )
    events = await store.list_events_for_artist("mbid-1")
    assert [(e.source, e.source_event_id) for e in events] == [("ticketmaster", "tm-1")]


@pytest.mark.asyncio
async def test_multi_artist_bill_keeps_one_row_per_artist(store: EventsStore):
    await store.apply_sweep_result("mbid-1", [_event()])
    await store.apply_sweep_result(
        "mbid-2", [_event(artist_mbid_lower="mbid-2", artist_name="Charli xcx")]
    )
    assert len(await store.list_events_for_artist("mbid-1")) == 1
    assert len(await store.list_events_for_artist("mbid-2")) == 1


@pytest.mark.asyncio
async def test_list_events_for_user_joins_follows_and_filters(store: EventsStore):
    await store.apply_sweep_result(
        "mbid-1",
        [
            _event("tm-past", local_date="2026-01-01"),
            _event("tm-late", local_date="2026-09-20"),
            _event("tm-soon", local_date="2026-08-28"),
        ],
        now=50.0,
    )
    # an artist user-a does not follow never surfaces
    await store.apply_sweep_result(
        "mbid-other", [_event("tm-x", artist_mbid_lower="mbid-other")]
    )

    rows = await store.list_events_for_user("user-a", min_local_date="2026-07-01")
    assert [r.event.source_event_id for r in rows] == ["tm-soon", "tm-late"]  # date asc
    assert rows[0].artist_mbid == "MBID-1"  # original case from the follow row

    assert await store.list_events_for_user("user-b", min_local_date="2026-07-01") == []

    fresh = await store.list_events_for_user(
        "user-a", min_local_date="2026-07-01", discovered_after=50.0
    )
    assert fresh == []  # nothing discovered after the sweep stamp


@pytest.mark.asyncio
async def test_prune_past_events(store: EventsStore):
    await store.apply_sweep_result(
        "mbid-1",
        [_event("tm-old", local_date="2026-06-01"), _event("tm-new", local_date="2026-12-01")],
    )
    deleted = await store.prune_past_events("2026-07-04")
    assert deleted == 1
    events = await store.list_events_for_artist("mbid-1")
    assert [e.source_event_id for e in events] == ["tm-new"]


@pytest.mark.asyncio
async def test_cursor_upserts(store: EventsStore):
    await store.update_cursor("mbid-1", "error", "boom")
    await store.update_cursor("mbid-1", "ok")

    def read(conn: sqlite3.Connection):
        return conn.execute(
            "SELECT last_status, last_error FROM artist_event_check WHERE artist_mbid_lower = 'mbid-1'"
        ).fetchone()

    row = await store._read(read)
    assert row["last_status"] == "ok"
    assert row["last_error"] is None


@pytest.mark.asyncio
async def test_tm_resolution_roundtrip_including_negative(store: EventsStore):
    assert await store.get_tm_resolution("mbid-1") is None
    await store.set_tm_resolution("mbid-1", "K8vZ9179LP7", "mbid", now=10.0)
    res = await store.get_tm_resolution("mbid-1")
    assert res is not None
    assert res.attraction_id == "K8vZ9179LP7"
    assert res.match_basis == "mbid"
    assert res.resolved_at == 10.0
    # negative result still carries a timestamp for the TTL
    await store.set_tm_resolution("mbid-1", None, "none", now=20.0)
    res = await store.get_tm_resolution("mbid-1")
    assert res.attraction_id is None
    assert res.match_basis == "none"
    assert res.resolved_at == 20.0


@pytest.mark.asyncio
async def test_skiddle_resolution_replace_and_negative_marker(store: EventsStore):
    assert await store.get_skiddle_resolution("mbid-1") is None
    await store.set_skiddle_resolution("mbid-1", ["123568993", "123604351"], now=10.0)
    res = await store.get_skiddle_resolution("mbid-1")
    assert res.artist_ids == ["123568993", "123604351"]
    assert res.resolved_at == 10.0
    # replace with an empty (negative) set: ids gone, marker stamped
    await store.set_skiddle_resolution("mbid-1", [], now=20.0)
    res = await store.get_skiddle_resolution("mbid-1")
    assert res.artist_ids == []
    assert res.resolved_at == 20.0


@pytest.mark.asyncio
async def test_cities_replace_all_and_ordering(store: EventsStore):
    liverpool = EventCity(
        city_name="Liverpool", country_code="GB", latitude=53.41, longitude=-2.98,
        radius_km=30.0, position=0,
    )
    chester = EventCity(
        city_name="Chester", country_code="GB", latitude=53.19, longitude=-2.89,
        radius_km=20.0, position=1,
    )
    await store.replace_cities("user-a", [chester, liverpool])
    cities = await store.list_cities("user-a")
    assert [c.city_name for c in cities] == ["Chester", "Liverpool"]  # list order wins
    assert cities[0].position == 0

    await store.replace_cities("user-a", [liverpool])
    assert [c.city_name for c in await store.list_cities("user-a")] == ["Liverpool"]

    assert await store.list_cities("user-b") == []


@pytest.mark.asyncio
async def test_seen_marker(store: EventsStore):
    assert await store.get_seen_at("user-a") == 0.0
    await store.mark_seen("user-a", now=123.0)
    assert await store.get_seen_at("user-a") == 123.0
    await store.mark_seen("user-a", now=456.0)
    assert await store.get_seen_at("user-a") == 456.0


@pytest.mark.asyncio
async def test_list_library_artists_reads_shared_index(store: EventsStore, db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE library_artists (
            mbid_lower TEXT PRIMARY KEY, mbid TEXT NOT NULL, name TEXT NOT NULL,
            album_count INTEGER DEFAULT 0, date_added INTEGER, raw_json TEXT NOT NULL
        );
        INSERT INTO library_artists VALUES ('mbid-lib', 'MBID-LIB', 'Crawlers', 1, 1, '{}');
        INSERT INTO library_artists VALUES ('mbid-nombid', '', 'Untagged', 1, 1, '{}');
        """
    )
    conn.commit()
    conn.close()
    artists = await store.list_library_artists()
    assert [(a.artist_mbid, a.artist_name) for a in artists] == [("MBID-LIB", "Crawlers")]


@pytest.mark.asyncio
async def test_cursor_ages(store: EventsStore):
    assert await store.cursor_ages() == {}
    await store.update_cursor("mbid-1", "ok")
    await store.update_cursor("mbid-2", "error", "boom")
    ages = await store.cursor_ages()
    assert set(ages) == {"mbid-1", "mbid-2"}
    assert all(v > 0 for v in ages.values())


@pytest.mark.asyncio
async def test_list_all_events_ignores_follows(store: EventsStore):
    await store.apply_sweep_result(
        "mbid-unfollowed",
        [_event("e1", artist_mbid_lower="mbid-unfollowed", local_date="2026-09-01")],
        now=50.0,
    )
    rows = await store.list_all_events(min_local_date="2026-08-01")
    assert len(rows) == 1
    assert rows[0].artist_mbid == "mbid-unfollowed"  # lowercase form, valid MBID
    assert await store.list_all_events(min_local_date="2026-10-01") == []
    assert await store.list_all_events("2026-08-01", discovered_after=50.0) == []


@pytest.mark.asyncio
async def test_user_delete_cascades_cities_and_seen(store: EventsStore, db_path: Path):
    await store.replace_cities(
        "user-a",
        [EventCity(city_name="Liverpool", country_code="GB", latitude=53.41,
                   longitude=-2.98, radius_km=30.0, position=0)],
    )
    await store.mark_seen("user-a")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("DELETE FROM auth_users WHERE id = 'user-a'")
    conn.commit()
    conn.close()

    assert await store.list_cities("user-a") == []
    assert await store.get_seen_at("user-a") == 0.0
