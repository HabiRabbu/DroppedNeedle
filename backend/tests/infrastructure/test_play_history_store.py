"""PlayHistoryStore tests (D6)."""

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.play_history_store import PlayHistoryStore


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT, role TEXT)"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, username, role) VALUES (?, ?, ?)",
            [("user-a", "alice", "user"), ("user-b", "bob", "user")],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def store(tmp_path: Path) -> PlayHistoryStore:
    db_path = tmp_path / "library.db"
    s = PlayHistoryStore(db_path=db_path, write_lock=threading.Lock())
    _seed_auth_users(db_path)
    return s


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    PlayHistoryStore(db_path=db_path, write_lock=lock)
    PlayHistoryStore(db_path=db_path, write_lock=lock)
    assert db_path.exists()


@pytest.mark.asyncio
async def test_insert_returns_id_and_roundtrips_fields(store: PlayHistoryStore):
    row_id = await store.insert(
        "user-a",
        track_name="Track",
        artist_name="Artist",
        album_name="Album",
        recording_mbid="rec-1",
        release_group_mbid="rg-1",
        duration_ms=180000,
        source="local",
        played_at="2026-06-20T10:00:00+00:00",
    )
    assert len(row_id) == 32
    recent = await store.recent("user-a")
    assert len(recent) == 1
    rec = recent[0]
    assert rec.id == row_id
    assert rec.track_name == "Track"
    assert rec.artist_name == "Artist"
    assert rec.album_name == "Album"
    assert rec.recording_mbid == "rec-1"
    assert rec.release_group_mbid == "rg-1"
    assert rec.duration_ms == 180000
    assert rec.source == "local"


@pytest.mark.asyncio
async def test_recent_is_ordered_by_played_at_desc(store: PlayHistoryStore):
    await store.insert("user-a", track_name="Old", artist_name="A", played_at="2026-06-20T08:00:00+00:00")
    await store.insert("user-a", track_name="New", artist_name="A", played_at="2026-06-20T12:00:00+00:00")
    await store.insert("user-a", track_name="Mid", artist_name="A", played_at="2026-06-20T10:00:00+00:00")
    recent = await store.recent("user-a")
    assert [r.track_name for r in recent] == ["New", "Mid", "Old"]


@pytest.mark.asyncio
async def test_recent_respects_limit(store: PlayHistoryStore):
    for i in range(5):
        await store.insert(
            "user-a", track_name=f"T{i}", artist_name="A", played_at=f"2026-06-20T0{i}:00:00+00:00"
        )
    assert len(await store.recent("user-a", limit=2)) == 2


@pytest.mark.asyncio
async def test_recent_is_user_scoped(store: PlayHistoryStore):
    await store.insert("user-a", track_name="A-track", artist_name="A", played_at="2026-06-20T10:00:00+00:00")
    await store.insert("user-b", track_name="B-track", artist_name="B", played_at="2026-06-20T10:00:00+00:00")
    assert [r.track_name for r in await store.recent("user-a")] == ["A-track"]
    assert [r.track_name for r in await store.recent("user-b")] == ["B-track"]


@pytest.mark.asyncio
async def test_cascade_on_user_delete(store: PlayHistoryStore, tmp_path: Path):
    await store.insert("user-a", track_name="T", artist_name="A", played_at="2026-06-20T10:00:00+00:00")
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM auth_users WHERE id = ?", ("user-a",))
        conn.commit()
    finally:
        conn.close()
    assert await store.recent("user-a") == []
