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
from core.exceptions import MediaAccountRelinkRequiredError
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
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, username, role) VALUES (?, ?, ?)",
            [("u1", "u1", "user"), ("u2", "u2", "user")],
        )
        conn.commit()
    finally:
        conn.close()


def _factory(
    store: UserConnectionsStore,
    *,
    app_key: str = "appkey",
    app_secret: str = "appsecret",
    media_enabled: bool = True,
):
    prefs = MagicMock()
    prefs.get_advanced_settings.return_value = SimpleNamespace(
        http_timeout=10, http_connect_timeout=5, http_max_connections=200
    )
    prefs.get_lastfm_connection.return_value = SimpleNamespace(
        api_key=app_key, shared_secret=app_secret
    )
    prefs.get_navidrome_connection_raw.return_value = SimpleNamespace(
        enabled=media_enabled, navidrome_url="http://nd.local"
    )
    prefs.get_jellyfin_connection.return_value = SimpleNamespace(
        enabled=media_enabled, jellyfin_url="http://jf.local"
    )
    prefs.get_plex_connection_raw.return_value = SimpleNamespace(
        enabled=media_enabled, plex_url="http://plex.local"
    )
    prefs.get_setting.return_value = "app-client-id"
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


# --- media servers: admin-owned URL + per-user credential (issue #138) ---


@pytest.mark.asyncio
async def test_resolve_navidrome_threads_app_url_and_user_credentials(store):
    await store.upsert("u1", "navidrome", {"username": "nduser", "password": "ndpass"})
    repo = await _factory(store).resolve_navidrome("u1")
    assert repo is not None
    assert repo._url == "http://nd.local"
    assert repo._username == "nduser"
    assert repo._password == "ndpass"
    assert repo.is_configured()


@pytest.mark.asyncio
async def test_resolve_navidrome_none_when_unlinked_or_incomplete(store):
    assert await _factory(store).resolve_navidrome("u1") is None
    await store.upsert("u1", "navidrome", {"username": "nduser", "password": ""})
    assert await _factory(store).resolve_navidrome("u1") is None


@pytest.mark.asyncio
async def test_resolve_navidrome_none_when_admin_disabled(store):
    await store.upsert("u1", "navidrome", {"username": "nduser", "password": "ndpass"})
    assert await _factory(store, media_enabled=False).resolve_navidrome("u1") is None


@pytest.mark.asyncio
async def test_resolve_jellyfin_threads_token_and_jellyfin_user_id(store):
    await store.upsert(
        "u1",
        "jellyfin",
        {"access_token": "jf-tok", "jellyfin_user_id": "jf-uid", "username": "jfuser"},
    )
    repo = await _factory(store).resolve_jellyfin("u1")
    assert repo is not None
    assert repo._base_url == "http://jf.local"
    assert repo._api_key == "jf-tok"
    assert repo._user_id == "jf-uid"


@pytest.mark.asyncio
async def test_resolve_jellyfin_none_when_unlinked_or_incomplete(store):
    assert await _factory(store).resolve_jellyfin("u1") is None
    await store.upsert("u1", "jellyfin", {"access_token": "jf-tok", "jellyfin_user_id": ""})
    assert await _factory(store).resolve_jellyfin("u1") is None


@pytest.mark.asyncio
async def test_resolve_jellyfin_none_when_admin_disabled(store):
    await store.upsert(
        "u1", "jellyfin", {"access_token": "jf-tok", "jellyfin_user_id": "jf-uid"}
    )
    assert await _factory(store, media_enabled=False).resolve_jellyfin("u1") is None


@pytest.mark.asyncio
async def test_resolve_plex_threads_token_and_app_client_id(store):
    await store.upsert(
        "u1", "plex", {"auth_token": "plex-tok", "plex_user_id": "px-uid", "username": "pxuser"}
    )
    repo = await _factory(store).resolve_plex("u1")
    assert repo is not None
    assert repo._url == "http://plex.local"
    assert repo._token == "plex-tok"
    assert repo._client_id == "app-client-id"
    assert repo.is_configured()


@pytest.mark.asyncio
async def test_resolve_plex_none_when_unlinked_or_admin_disabled(store):
    assert await _factory(store).resolve_plex("u1") is None
    await store.upsert("u1", "plex", {"auth_token": "plex-tok"})
    assert await _factory(store, media_enabled=False).resolve_plex("u1") is None


@pytest.mark.asyncio
async def test_playlist_resolvers_use_linked_credentials_and_user_cache_scope(store):
    await store.upsert(
        "u1", "navidrome", {"username": "nduser", "password": "ndpass"}
    )
    await store.upsert(
        "u1",
        "jellyfin",
        {
            "access_token": "jf-tok",
            "jellyfin_user_id": "jf-uid",
            "username": "jfuser",
        },
    )
    await store.upsert(
        "u1",
        "plex",
        {
            "auth_token": "account-tok",
            "server_access_token": "server-tok",
            "username": "plexuser",
        },
    )
    factory = _factory(store)

    navidrome = await factory.resolve_navidrome_playlist("u1")
    jellyfin = await factory.resolve_jellyfin_playlist("u1")
    plex = await factory.resolve_plex_playlist("u1")

    assert navidrome is not None
    assert navidrome.account_mode == "linked"
    assert navidrome.account_label == "nduser"
    assert navidrome.repository._cache_scope.startswith("user:u1:")
    assert jellyfin is not None
    assert jellyfin.account_label == "jfuser"
    assert jellyfin.repository._api_key == "jf-tok"
    assert jellyfin.repository._cache_scope.startswith("user:u1:")
    assert plex is not None
    assert plex.account_label == "plexuser"
    assert plex.repository._token == "server-tok"
    assert plex.repository._cache_scope.startswith("user:u1:")


@pytest.mark.asyncio
async def test_playlist_resolvers_return_none_only_when_user_has_no_link(store):
    factory = _factory(store)
    assert await factory.resolve_navidrome_playlist("u1") is None
    assert await factory.resolve_jellyfin_playlist("u1") is None
    assert await factory.resolve_plex_playlist("u1") is None


@pytest.mark.asyncio
async def test_enabled_but_unreadable_media_link_fails_closed(store):
    await store.upsert(
        "u1",
        "jellyfin",
        {"access_token": "jf-tok", "jellyfin_user_id": "jf-uid"},
    )
    conn = sqlite3.connect(store.db_path)
    try:
        conn.execute(
            "UPDATE user_connections SET connection_data = ? "
            "WHERE user_id = ? AND service = ?",
            ("unreadable", "u1", "jellyfin"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MediaAccountRelinkRequiredError):
        await _factory(store).resolve_jellyfin_playlist("u1")


@pytest.mark.asyncio
async def test_two_users_get_distinct_playlist_cache_scopes(store):
    for user_id, username in (("u1", "alice"), ("u2", "bob")):
        await store.upsert(
            user_id,
            "jellyfin",
            {
                "access_token": f"token-{user_id}",
                "jellyfin_user_id": f"jf-{user_id}",
                "username": username,
            },
        )
    factory = _factory(store)
    alice = await factory.resolve_jellyfin_playlist("u1")
    bob = await factory.resolve_jellyfin_playlist("u2")

    assert alice is not None and bob is not None
    assert alice.repository._cache_scope.startswith("user:u1:")
    assert bob.repository._cache_scope.startswith("user:u2:")
    assert alice.repository._cache_scope != bob.repository._cache_scope
    assert alice.repository._api_key != bob.repository._api_key


@pytest.mark.asyncio
async def test_relink_changes_playlist_cache_generation(store):
    await store.upsert(
        "u1",
        "jellyfin",
        {
            "access_token": "old-token",
            "jellyfin_user_id": "jf-u1",
            "username": "alice",
        },
    )
    factory = _factory(store)
    before = await factory.resolve_jellyfin_playlist("u1")

    await store.upsert(
        "u1",
        "jellyfin",
        {
            "access_token": "new-token",
            "jellyfin_user_id": "jf-u1",
            "username": "alice",
        },
    )
    after = await factory.resolve_jellyfin_playlist("u1")

    assert before is not None and after is not None
    assert before.repository._cache_scope.startswith("user:u1:")
    assert after.repository._cache_scope.startswith("user:u1:")
    assert before.repository._cache_scope != after.repository._cache_scope


@pytest.mark.asyncio
async def test_legacy_plex_link_is_upgraded_to_server_specific_token(
    store, monkeypatch
):
    await store.upsert(
        "u1",
        "plex",
        {
            "auth_token": "account-token",
            "plex_user_id": "plex-user",
            "username": "alice",
        },
    )

    from repositories.plex_repository import PlexRepository

    async def machine_id(_self):
        return "machine-1"

    async def server_token(_self, auth_token, client_id, machine_id):
        assert (auth_token, client_id, machine_id) == (
            "account-token",
            "app-client-id",
            "machine-1",
        )
        return "server-token"

    monkeypatch.setattr(PlexRepository, "get_machine_identifier", machine_id)
    monkeypatch.setattr(PlexRepository, "get_server_access_token", server_token)

    resolution = await _factory(store).resolve_plex_playlist("u1")

    assert resolution is not None
    assert resolution.repository._token == "server-token"
    assert (await store.get("u1", "plex"))["server_access_token"] == "server-token"


@pytest.mark.asyncio
async def test_media_server_linked_checks_mirror_resolvers(store):
    factory = _factory(store)
    assert await factory.is_navidrome_linked("u1") is False
    assert await factory.is_jellyfin_linked("u1") is False
    assert await factory.is_plex_linked("u1") is False

    await store.upsert("u1", "navidrome", {"username": "n", "password": "p"})
    await store.upsert("u1", "jellyfin", {"access_token": "t", "jellyfin_user_id": "i"})
    await store.upsert("u1", "plex", {"auth_token": "t"})
    assert await factory.is_navidrome_linked("u1") is True
    assert await factory.is_jellyfin_linked("u1") is True
    assert await factory.is_plex_linked("u1") is True

    disabled = _factory(store, media_enabled=False)
    assert await disabled.is_navidrome_linked("u1") is False
    assert await disabled.is_jellyfin_linked("u1") is False
    assert await disabled.is_plex_linked("u1") is False


@pytest.mark.asyncio
async def test_validate_navidrome_credentials_pings_with_user_credentials(store, monkeypatch):
    seen: dict = {}

    async def fake_validate(self):
        seen["url"] = self._url
        seen["username"] = self._username
        seen["password"] = self._password
        return True, "Connected"

    from repositories.navidrome_repository import NavidromeRepository

    monkeypatch.setattr(NavidromeRepository, "validate_connection", fake_validate)
    ok, message = await _factory(store).validate_navidrome_credentials("nduser", "ndpass")
    assert ok is True
    assert seen == {"url": "http://nd.local", "username": "nduser", "password": "ndpass"}


@pytest.mark.asyncio
async def test_validate_navidrome_credentials_fails_when_admin_disabled(store):
    ok, message = await _factory(store, media_enabled=False).validate_navidrome_credentials(
        "nduser", "ndpass"
    )
    assert ok is False
    assert "not configured" in message
