import sqlite3
import threading

import pytest

from infrastructure.persistence.navidrome_folder_preferences_store import (
    NavidromeFolderPreferencesStore,
)

pytestmark = pytest.mark.asyncio


def _seed_users(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO auth_users (id) VALUES (?)", [("alice",), ("bob",)]
        )


async def test_store_is_idempotent_and_defaults_to_all(tmp_path):
    path = tmp_path / "library.db"
    _seed_users(path)
    lock = threading.Lock()
    first = NavidromeFolderPreferencesStore(path, lock)
    second = NavidromeFolderPreferencesStore(path, lock)

    assert (await first.get("alice")).mode == "all"
    assert (await second.get("alice")).selected_folder_ids == ()


async def test_selected_ids_are_canonical_and_replaced_atomically(tmp_path):
    path = tmp_path / "library.db"
    _seed_users(path)
    store = NavidromeFolderPreferencesStore(path, threading.Lock())

    saved = await store.set(
        "alice",
        mode="selected",
        selected_folder_ids=("folder-b", "folder-a", "folder-b"),
        server_identity="server-1",
    )
    assert saved.selected_folder_ids == ("folder-a", "folder-b")

    await store.set(
        "alice",
        mode="selected",
        selected_folder_ids=("folder-c",),
        server_identity="server-1",
    )
    assert (await store.get("alice")).selected_folder_ids == ("folder-c",)


async def test_user_delete_cascades_without_affecting_other_user(tmp_path):
    path = tmp_path / "library.db"
    _seed_users(path)
    store = NavidromeFolderPreferencesStore(path, threading.Lock())
    await store.set("alice", mode="selected", selected_folder_ids=("a",))
    await store.set("bob", mode="selected", selected_folder_ids=("b",))

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM auth_users WHERE id = 'alice'")

    assert (await store.get("alice")).mode == "all"
    assert (await store.get("bob")).selected_folder_ids == ("b",)
