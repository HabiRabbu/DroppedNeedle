import sqlite3
import threading

import pytest

from infrastructure.persistence.compat_bookmark_store import CompatBookmarkStore
from infrastructure.persistence.compat_play_queue_store import CompatPlayQueueStore


def _seed_user(db_path, user_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, display_name TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO auth_users (id, display_name) VALUES (?, ?)",
        (user_id, user_id),
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_play_queue_store_is_idempotent_atomic_and_preserves_duplicates(tmp_path):
    db_path = tmp_path / "library.db"
    _seed_user(db_path, "alice")
    lock = threading.Lock()
    first = CompatPlayQueueStore(db_path, lock)
    second = CompatPlayQueueStore(db_path, lock)

    await first.replace(
        "alice",
        ("one", "two", "one"),
        current_index=2,
        position_ms=1234,
        changed_by_client="client",
    )

    queue = await second.get("alice")
    assert queue.file_ids == ("one", "two", "one")
    assert queue.current_index == 2
    assert queue.position_ms == 1234


@pytest.mark.asyncio
async def test_playback_state_stores_cascade_with_user_deletion(tmp_path):
    db_path = tmp_path / "library.db"
    _seed_user(db_path, "alice")
    lock = threading.Lock()
    queues = CompatPlayQueueStore(db_path, lock)
    bookmarks = CompatBookmarkStore(db_path, lock)
    CompatPlayQueueStore(db_path, lock)
    CompatBookmarkStore(db_path, lock)

    await queues.replace(
        "alice", ("one",), current_index=0, position_ms=10, changed_by_client="c"
    )
    await bookmarks.upsert("alice", "one", 20, "note")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("DELETE FROM auth_users WHERE id = 'alice'")
    conn.commit()
    conn.close()

    assert (await queues.get("alice")).file_ids == ()
    assert await bookmarks.list("alice") == []


@pytest.mark.asyncio
async def test_bookmark_upsert_preserves_created_time_and_is_user_scoped(tmp_path):
    db_path = tmp_path / "library.db"
    _seed_user(db_path, "alice")
    _seed_user(db_path, "bob")
    store = CompatBookmarkStore(db_path, threading.Lock())

    await store.upsert("alice", "one", 10, "first")
    original = (await store.list("alice"))[0]
    await store.upsert("alice", "one", 20, "changed")
    changed = (await store.list("alice"))[0]

    assert changed.created_at == original.created_at
    assert changed.position_ms == 20
    assert changed.comment == "changed"
    assert await store.list("bob") == []
