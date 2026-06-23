"""D10 upgrade-continuity backfill: seed the first admin's per-user connections +
listening prefs from the global config. Idempotent; fresh-install + other-user no-op."""

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.crypto import init_crypto
from infrastructure.persistence.auth_store import UserRecord
from infrastructure.persistence.user_connections_store import UserConnectionsStore
from infrastructure.persistence.user_listening_prefs_store import UserListeningPrefsStore
from main import _migrate_global_connection_to_first_admin


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
            [("admin-1", "root", "admin"), ("user-b", "bob", "user")],
        )
        conn.commit()
    finally:
        conn.close()


def _admin() -> UserRecord:
    return UserRecord(id="admin-1", display_name="root", role="admin", created_at="2024-01-01T00:00:00Z")


def _auth_store(admin: UserRecord | None):
    store = AsyncMock()
    store.get_first_admin.return_value = admin
    return store


def _prefs_service(
    *,
    lb_enabled=True,
    lb_token="lb-tok",
    lb_user="lbuser",
    lf_session="sk-secret",
    lf_user="lfuser",
    scrobble_lastfm=True,
    scrobble_lb=True,
    source="lastfm",
):
    m = MagicMock()
    m.get_listenbrainz_connection.return_value = SimpleNamespace(
        enabled=lb_enabled, user_token=lb_token, username=lb_user
    )
    m.get_lastfm_connection.return_value = SimpleNamespace(
        session_key=lf_session, username=lf_user, api_key="appkey", shared_secret="appsecret"
    )
    m.get_scrobble_settings.return_value = SimpleNamespace(
        scrobble_to_lastfm=scrobble_lastfm, scrobble_to_listenbrainz=scrobble_lb
    )
    m.get_primary_music_source.return_value = SimpleNamespace(source=source)
    return m


@pytest.fixture
def stores(tmp_path: Path):
    db = tmp_path / "library.db"
    conn_store = UserConnectionsStore(db_path=db, write_lock=threading.Lock())
    prefs_store = UserListeningPrefsStore(db_path=db, write_lock=threading.Lock())
    _seed_auth_users(db)
    return conn_store, prefs_store


@pytest.mark.asyncio
async def test_seeds_connections_and_prefs(stores):
    conn_store, prefs_store = stores
    await _migrate_global_connection_to_first_admin(
        _auth_store(_admin()), _prefs_service(), conn_store, prefs_store
    )
    lb = await conn_store.get("admin-1", "listenbrainz")
    assert lb == {"user_token": "lb-tok", "username": "lbuser"}
    lf = await conn_store.get("admin-1", "lastfm")
    assert lf == {"session_key": "sk-secret", "username": "lfuser"}
    # app key/secret must not be copied into the per-user connection
    assert "api_key" not in lf and "shared_secret" not in lf

    prefs = await prefs_store.get("admin-1")
    assert prefs.scrobble_to_lastfm is True
    assert prefs.scrobble_to_listenbrainz is True
    assert prefs.primary_music_source == "lastfm"


@pytest.mark.asyncio
async def test_second_run_is_noop(stores):
    conn_store, prefs_store = stores
    prefs_svc = _prefs_service()
    await _migrate_global_connection_to_first_admin(_auth_store(_admin()), prefs_svc, conn_store, prefs_store)
    await _migrate_global_connection_to_first_admin(_auth_store(_admin()), prefs_svc, conn_store, prefs_store)
    records = await conn_store.list_for_user("admin-1")
    assert sorted(r.service for r in records) == ["lastfm", "listenbrainz"]
    assert len(records) == 2


@pytest.mark.asyncio
async def test_fresh_install_no_admin_noop(stores):
    conn_store, prefs_store = stores
    await _migrate_global_connection_to_first_admin(
        _auth_store(None), _prefs_service(), conn_store, prefs_store
    )
    assert await conn_store.list_for_user("admin-1") == []


@pytest.mark.asyncio
async def test_skips_service_admin_already_has(stores):
    conn_store, prefs_store = stores
    await conn_store.upsert("admin-1", "lastfm", {"session_key": "existing", "username": "existing"})
    await _migrate_global_connection_to_first_admin(
        _auth_store(_admin()), _prefs_service(), conn_store, prefs_store
    )
    assert (await conn_store.get("admin-1", "lastfm")) == {"session_key": "existing", "username": "existing"}
    assert (await conn_store.get("admin-1", "listenbrainz")) == {"user_token": "lb-tok", "username": "lbuser"}


@pytest.mark.asyncio
async def test_other_user_untouched(stores):
    conn_store, prefs_store = stores
    await _migrate_global_connection_to_first_admin(
        _auth_store(_admin()), _prefs_service(), conn_store, prefs_store
    )
    assert await conn_store.list_for_user("user-b") == []
    assert (await prefs_store.get("user-b")).updated_at == ""


@pytest.mark.asyncio
async def test_no_global_connection_seeds_nothing(stores):
    conn_store, prefs_store = stores
    prefs_svc = _prefs_service(
        lb_enabled=False, lf_session="", scrobble_lastfm=False, scrobble_lb=False, source="listenbrainz"
    )
    await _migrate_global_connection_to_first_admin(_auth_store(_admin()), prefs_svc, conn_store, prefs_store)
    assert await conn_store.list_for_user("admin-1") == []
    # no meaningful prefs to carry over, so no row written
    assert (await prefs_store.get("admin-1")).updated_at == ""
