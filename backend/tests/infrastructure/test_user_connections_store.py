"""UserConnectionsStore tests (AMU-1/AMU-3)."""

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.crypto import init_crypto
from infrastructure.persistence.user_connections_store import UserConnectionsStore


@pytest.fixture(autouse=True)
def _crypto(tmp_path: Path) -> None:
    init_crypto(tmp_path / "config")


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT, role TEXT)"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, username, role) VALUES (?, ?, ?)",
            [("user-a", "alice", "user"), ("user-b", "bob", "user"), ("admin-1", "root", "admin")],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def store(tmp_path: Path) -> UserConnectionsStore:
    db_path = tmp_path / "library.db"
    s = UserConnectionsStore(db_path=db_path, write_lock=threading.Lock())
    _seed_auth_users(db_path)
    return s


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    UserConnectionsStore(db_path=db_path, write_lock=lock)
    UserConnectionsStore(db_path=db_path, write_lock=lock)
    assert db_path.exists()


@pytest.mark.asyncio
async def test_upsert_get_roundtrip(store: UserConnectionsStore):
    await store.upsert("user-a", "listenbrainz", {"user_token": "tok-123", "username": "alice"})
    data = await store.get("user-a", "listenbrainz")
    assert data == {"user_token": "tok-123", "username": "alice"}


@pytest.mark.asyncio
async def test_ciphertext_on_disk_is_not_plaintext(store: UserConnectionsStore, tmp_path: Path):
    await store.upsert("user-a", "lastfm", {"session_key": "sk-secret-xyz", "username": "alice"})
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        raw = conn.execute(
            "SELECT connection_data FROM user_connections WHERE user_id = ? AND service = ?",
            ("user-a", "lastfm"),
        ).fetchone()[0]
    finally:
        conn.close()
    assert "sk-secret-xyz" not in raw
    assert raw != json.dumps({"session_key": "sk-secret-xyz", "username": "alice"})


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(store: UserConnectionsStore):
    assert await store.get("user-a", "listenbrainz") is None


@pytest.mark.asyncio
async def test_get_returns_none_when_disabled(store: UserConnectionsStore):
    await store.upsert("user-a", "lastfm", {"session_key": "sk", "username": "alice"})
    await store.set_enabled("user-a", "lastfm", False)
    assert await store.get("user-a", "lastfm") is None


@pytest.mark.asyncio
async def test_upsert_replaces_not_duplicates(store: UserConnectionsStore):
    await store.upsert("user-a", "lastfm", {"session_key": "sk1", "username": "alice"})
    await store.upsert("user-a", "lastfm", {"session_key": "sk2", "username": "alice2"})
    records = await store.list_for_user("user-a")
    lastfm = [r for r in records if r.service == "lastfm"]
    assert len(lastfm) == 1
    assert (await store.get("user-a", "lastfm"))["session_key"] == "sk2"


@pytest.mark.asyncio
async def test_list_for_user_exposes_username_not_secret(store: UserConnectionsStore):
    await store.upsert("user-a", "listenbrainz", {"user_token": "tok", "username": "alice"})
    records = await store.list_for_user("user-a")
    assert len(records) == 1
    rec = records[0]
    assert rec.service == "listenbrainz"
    assert rec.username == "alice"
    assert rec.enabled is True
    assert "tok" not in str(rec.__struct_fields__)


@pytest.mark.asyncio
async def test_list_for_user_is_scoped(store: UserConnectionsStore):
    await store.upsert("user-a", "lastfm", {"session_key": "sk", "username": "alice"})
    await store.upsert("user-b", "lastfm", {"session_key": "sk", "username": "bob"})
    assert len(await store.list_for_user("user-a")) == 1
    assert len(await store.list_for_user("user-b")) == 1
    assert (await store.list_for_user("user-a"))[0].username == "alice"


@pytest.mark.asyncio
async def test_delete_removes(store: UserConnectionsStore):
    await store.upsert("user-a", "lastfm", {"session_key": "sk", "username": "alice"})
    assert await store.delete("user-a", "lastfm") is True
    assert await store.get("user-a", "lastfm") is None
    assert await store.delete("user-a", "lastfm") is False


@pytest.mark.asyncio
async def test_get_returns_none_on_undecryptable_ciphertext(store: UserConnectionsStore, tmp_path: Path):
    # simulate a rotated/lost key
    await store.upsert("user-a", "listenbrainz", {"user_token": "tok", "username": "alice"})
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute(
            "UPDATE user_connections SET connection_data = ? WHERE user_id = ? AND service = ?",
            ("not-a-fernet-token", "user-a", "listenbrainz"),
        )
        conn.commit()
    finally:
        conn.close()
    # degrades to None per resolver contract, not raise
    assert await store.get("user-a", "listenbrainz") is None


@pytest.mark.asyncio
async def test_list_for_user_excludes_disabled(store: UserConnectionsStore):
    await store.upsert("user-a", "lastfm", {"session_key": "sk", "username": "alice"})
    await store.set_enabled("user-a", "lastfm", False)
    assert await store.list_for_user("user-a") == []


@pytest.mark.asyncio
async def test_cascade_on_user_delete(store: UserConnectionsStore, tmp_path: Path):
    await store.upsert("user-a", "lastfm", {"session_key": "sk", "username": "alice"})
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM auth_users WHERE id = ?", ("user-a",))
        conn.commit()
    finally:
        conn.close()
    assert await store.list_for_user("user-a") == []


@pytest.mark.asyncio
async def test_get_service_token_returns_earliest_connected_token(store: UserConnectionsStore):
    # two users connect ListenBrainz; the earliest (admin/owner) token is borrowed
    # for app-wide public reads
    await store.upsert("user-a", "listenbrainz", {"user_token": "owner-tok", "username": "alice"})
    await store.upsert("user-b", "listenbrainz", {"user_token": "other-tok", "username": "bob"})

    token = await store.get_service_token("listenbrainz")
    assert token == "owner-tok"


@pytest.mark.asyncio
async def test_get_service_token_none_when_unconnected(store: UserConnectionsStore):
    assert await store.get_service_token("listenbrainz") is None


@pytest.mark.asyncio
async def test_get_service_token_skips_disabled(store: UserConnectionsStore):
    await store.upsert("user-a", "listenbrainz", {"user_token": "tok-1", "username": "alice"})
    await store.set_enabled("user-a", "listenbrainz", False)
    assert await store.get_service_token("listenbrainz") is None
