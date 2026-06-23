"""PerUserClientFactory LB/Last.fm asymmetry seam (B5).

Pins credential threading and the None contract that mocked-factory scrobble tests
can't catch: swapped username/token, a dropped missing-app-keys guard, or session_key
passed where api_key belongs would pass every other test but is caught here.
"""

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.config import get_settings
from infrastructure.crypto import init_crypto
from infrastructure.persistence.user_connections_store import UserConnectionsStore
from services.per_user_client_factory import PerUserClientFactory


@pytest.fixture(autouse=True)
def _crypto(tmp_path: Path) -> None:
    init_crypto(tmp_path / "config")


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT, role TEXT)")
        conn.execute("INSERT OR IGNORE INTO auth_users (id, username, role) VALUES (?, ?, ?)", ("u1", "u1", "user"))
        conn.commit()
    finally:
        conn.close()


def _factory(store: UserConnectionsStore, *, app_key: str = "appkey", app_secret: str = "appsecret"):
    prefs = MagicMock()
    prefs.get_advanced_settings.return_value = SimpleNamespace(
        http_timeout=10, http_connect_timeout=5, http_max_connections=200
    )
    prefs.get_lastfm_connection.return_value = SimpleNamespace(
        api_key=app_key, shared_secret=app_secret
    )
    return PerUserClientFactory(
        connections_store=store,
        preferences_service=prefs,
        cache=MagicMock(),
        settings=get_settings(),
    )


@pytest.fixture
def store(tmp_path: Path) -> UserConnectionsStore:
    db = tmp_path / "library.db"
    s = UserConnectionsStore(db_path=db, write_lock=threading.Lock())
    _seed_auth_users(db)
    return s


@pytest.mark.asyncio
async def test_resolve_listenbrainz_threads_username_and_token(store):
    await store.upsert("u1", "listenbrainz", {"user_token": "tok-1", "username": "lbuser"})
    repo = await _factory(store).resolve_listenbrainz("u1")
    assert repo is not None
    assert repo._username == "lbuser"
    assert repo._user_token == "tok-1"


@pytest.mark.asyncio
async def test_resolve_listenbrainz_none_when_absent(store):
    assert await _factory(store).resolve_listenbrainz("u1") is None


@pytest.mark.asyncio
async def test_resolve_listenbrainz_none_when_token_empty(store):
    await store.upsert("u1", "listenbrainz", {"user_token": "", "username": "lbuser"})
    assert await _factory(store).resolve_listenbrainz("u1") is None


@pytest.mark.asyncio
async def test_resolve_lastfm_uses_global_app_keys_and_user_session(store):
    await store.upsert("u1", "lastfm", {"session_key": "sk-1", "username": "lfuser"})
    repo = await _factory(store).resolve_lastfm("u1")
    assert repo is not None
    # global app credentials
    assert repo._api_key == "appkey"
    assert repo._shared_secret == "appsecret"
    # plus the per-user session key
    assert repo._session_key == "sk-1"
    # Last.fm holds no per-user username on the instance; reads take it per-call
    assert not hasattr(repo, "_username")


@pytest.mark.asyncio
async def test_resolve_lastfm_none_when_session_empty(store):
    await store.upsert("u1", "lastfm", {"session_key": "", "username": "lfuser"})
    assert await _factory(store).resolve_lastfm("u1") is None


@pytest.mark.asyncio
async def test_resolve_lastfm_none_when_global_app_keys_missing(store):
    await store.upsert("u1", "lastfm", {"session_key": "sk-1", "username": "lfuser"})
    assert await _factory(store, app_key="", app_secret="").resolve_lastfm("u1") is None


@pytest.mark.asyncio
async def test_resolve_lastfm_username(store):
    assert await _factory(store).resolve_lastfm_username("u1") is None
    await store.upsert("u1", "lastfm", {"session_key": "sk", "username": "lfuser"})
    assert await _factory(store).resolve_lastfm_username("u1") == "lfuser"
