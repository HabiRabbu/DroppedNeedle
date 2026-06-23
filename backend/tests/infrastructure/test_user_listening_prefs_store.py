"""UserListeningPrefsStore tests."""

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.user_listening_prefs_store import UserListeningPrefsStore


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
def store(tmp_path: Path) -> UserListeningPrefsStore:
    db_path = tmp_path / "library.db"
    s = UserListeningPrefsStore(db_path=db_path, write_lock=threading.Lock())
    _seed_auth_users(db_path)
    return s


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    UserListeningPrefsStore(db_path=db_path, write_lock=lock)
    UserListeningPrefsStore(db_path=db_path, write_lock=lock)
    assert db_path.exists()


@pytest.mark.asyncio
async def test_missing_row_returns_defaults(store: UserListeningPrefsStore):
    prefs = await store.get("user-a")
    assert prefs.user_id == "user-a"
    assert prefs.scrobble_to_lastfm is False
    assert prefs.scrobble_to_listenbrainz is False
    assert prefs.primary_music_source == "listenbrainz"


@pytest.mark.asyncio
async def test_full_upsert_roundtrip(store: UserListeningPrefsStore):
    await store.upsert(
        "user-a",
        scrobble_to_lastfm=True,
        scrobble_to_listenbrainz=True,
        primary_music_source="lastfm",
    )
    prefs = await store.get("user-a")
    assert prefs.scrobble_to_lastfm is True
    assert prefs.scrobble_to_listenbrainz is True
    assert prefs.primary_music_source == "lastfm"


@pytest.mark.asyncio
async def test_partial_upsert_preserves_other_columns(store: UserListeningPrefsStore):
    await store.upsert("user-a", scrobble_to_lastfm=True)
    await store.upsert("user-a", primary_music_source="lastfm")
    prefs = await store.get("user-a")
    assert prefs.scrobble_to_lastfm is True
    assert prefs.scrobble_to_listenbrainz is False
    assert prefs.primary_music_source == "lastfm"


@pytest.mark.asyncio
async def test_upsert_is_user_scoped(store: UserListeningPrefsStore):
    await store.upsert("user-a", scrobble_to_lastfm=True)
    assert (await store.get("user-a")).scrobble_to_lastfm is True
    assert (await store.get("user-b")).scrobble_to_lastfm is False


@pytest.mark.asyncio
async def test_cascade_on_user_delete(store: UserListeningPrefsStore, tmp_path: Path):
    await store.upsert("user-a", scrobble_to_lastfm=True)
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM auth_users WHERE id = ?", ("user-a",))
        conn.commit()
        remaining = conn.execute(
            "SELECT COUNT(*) FROM user_listening_prefs WHERE user_id = ?", ("user-a",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert remaining == 0
