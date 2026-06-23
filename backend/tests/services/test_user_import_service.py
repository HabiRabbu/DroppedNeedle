"""Phase 6 (AuthMultiUser D5) UserImportService tests: idempotent admin import of
Jellyfin/Plex users into pre-provisioned auth_users + pre-linked auth_providers,
driven through a real temp AuthStore with faked media repositories."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.exceptions import RegistrationError
from infrastructure.persistence.auth_store import AuthStore
from repositories.jellyfin_models import JellyfinUser
from repositories.plex_models import PlexAccount
from services.plex_user_auth_service import PlexUserAuthService
from services.user_import_service import UserImportService


class _FakeJellyfinRepo:
    def __init__(self, users):
        self._users = users

    async def get_users(self):
        return list(self._users)


class _FakePlexRepo:
    def __init__(self, accounts):
        self._accounts = accounts

    async def enumerate_users(self):
        return list(self._accounts)


class _FakePrefs:
    def __init__(self, jellyfin_url="https://jf.example.com"):
        self._url = jellyfin_url

    def get_jellyfin_connection(self):
        return SimpleNamespace(jellyfin_url=self._url)


def _service(store, *, jellyfin=None, plex=None, prefs=None):
    return UserImportService(
        store,
        _FakeJellyfinRepo(jellyfin or []),
        _FakePlexRepo(plex or []),
        prefs or _FakePrefs(),
    )


def test_import_jellyfin_creates_user_and_pre_linked_provider(tmp_path):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        svc = _service(store, jellyfin=[JellyfinUser(id="jf-1", name="Alice")])

        result = await svc.import_users("jellyfin", ["jf-1"])

        assert len(result.imported) == 1
        assert result.linked == []
        assert result.skipped == []
        user = result.imported[0]
        assert user.role == "user"  # forced - not from any request body (D5)
        assert user.email is None  # Jellyfin exposes no email
        assert user.username == "alice"
        assert user.username_display == "Alice"
        assert user.avatar_url is None  # unguarded Jellyfin URL not persisted

        provider = await store.get_auth_provider("jellyfin", "jf-1")
        assert provider is not None
        assert provider.user_id == user.id
        assert provider.provider_data is None  # no password, no token (AMU-3)

    asyncio.run(scenario())


def test_reimport_is_idempotent(tmp_path):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        svc = _service(store, jellyfin=[JellyfinUser(id="jf-1", name="Alice")])

        first = await svc.import_users("jellyfin", ["jf-1"])
        assert len(first.imported) == 1
        before = await store.count_users()

        second = await svc.import_users("jellyfin", ["jf-1"])
        assert second.imported == []
        assert second.skipped == ["jf-1"]
        assert await store.count_users() == before  # no duplicate row

    asyncio.run(scenario())


def test_jellyfin_import_never_consults_email(tmp_path):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        calls: list[str] = []
        original = store.get_user_by_email

        async def spy(email):
            calls.append(email)
            return await original(email)

        store.get_user_by_email = spy  # type: ignore[method-assign]
        svc = _service(store, jellyfin=[JellyfinUser(id="jf-1", name="Alice")])

        await svc.import_users("jellyfin", ["jf-1"])

        assert calls == []  # idempotency keys only on (provider, provider_uid)

    asyncio.run(scenario())


def test_username_dedup_for_same_display_name(tmp_path):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        svc = _service(
            store,
            jellyfin=[JellyfinUser(id="jf-1", name="John"), JellyfinUser(id="jf-2", name="John")],
        )

        result = await svc.import_users("jellyfin", ["jf-1", "jf-2"])

        assert len(result.imported) == 2
        usernames = sorted(u.username for u in result.imported)
        assert usernames == ["john", "john-2"]

    asyncio.run(scenario())


def test_plex_uuid_join_matches_first_login(tmp_path, monkeypatch):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        account = PlexAccount(
            uuid="plex-uuid-1",
            username="bob",
            title="Bob",
            email=None,
            thumb="https://plex.tv/u/1/avatar",
            source="home",
        )
        svc = _service(store, plex=[account])

        result = await svc.import_users("plex", ["plex-uuid-1"])
        assert len(result.imported) == 1
        imported = result.imported[0]
        assert imported.avatar_url == "https://plex.tv/u/1/avatar"  # real thumb persisted

        provider = await store.get_auth_provider("plex", "plex-uuid-1")
        assert provider is not None
        assert provider.user_id == imported.id

        # First SSO login: _find_or_create_user keys on profile["uuid"]. It must
        # return the pre-provisioned user and NOT create a second account.
        monkeypatch.setattr("services.plex_user_auth_service.encrypt", lambda s: s)
        plex_auth = PlexUserAuthService(store, _FakePlexRepo([]), _FakePrefs())
        before = await store.count_users()
        profile = {"uuid": "plex-uuid-1", "email": None, "display_name": "Bob", "thumb": None}
        logged_in = await plex_auth._find_or_create_user(profile, auth_token="tok")
        assert logged_in.id == imported.id
        assert await store.count_users() == before

    asyncio.run(scenario())


def test_email_collision_links_to_existing_user(tmp_path, monkeypatch):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        existing = await store.create_user(
            id="u-existing",
            display_name="Existing",
            role="user",
            email="a@b.c",
            username="existing",
            username_display="Existing",
        )
        account = PlexAccount(
            uuid="plex-uuid-2",
            username="alias",
            title="Alias",
            email="a@b.c",
            thumb=None,
            source="friend",
        )
        svc = _service(store, plex=[account])
        before = await store.count_users()

        result = await svc.import_users("plex", ["plex-uuid-2"])

        assert result.imported == []
        assert len(result.linked) == 1
        assert result.linked[0].id == existing.id
        assert await store.count_users() == before  # L1: no new auth_users row

        provider = await store.get_auth_provider("plex", "plex-uuid-2")
        assert provider is not None
        assert provider.user_id == existing.id
        assert provider.provider_data is None

        refreshed = await store.get_user_by_id(existing.id)
        assert refreshed.email == "a@b.c"  # untouched
        assert refreshed.username == "existing"

        # Subsequent SSO login resolves into the existing account, not a new one.
        monkeypatch.setattr("services.plex_user_auth_service.encrypt", lambda s: s)
        plex_auth = PlexUserAuthService(store, _FakePlexRepo([]), _FakePrefs())
        profile = {"uuid": "plex-uuid-2", "email": "a@b.c", "display_name": "Alias", "thumb": None}
        logged_in = await plex_auth._find_or_create_user(profile, auth_token="tok")
        assert logged_in.id == existing.id

    asyncio.run(scenario())


def test_list_jellyfin_marks_already_imported(tmp_path):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        svc = _service(
            store,
            jellyfin=[JellyfinUser(id="jf-1", name="Alice"), JellyfinUser(id="jf-2", name="Bob")],
        )
        await svc.import_users("jellyfin", ["jf-1"])

        candidates = await svc.list_jellyfin_users()
        by_uid = {c.provider_uid: c for c in candidates}
        assert by_uid["jf-1"].already_imported is True
        assert by_uid["jf-2"].already_imported is False
        assert by_uid["jf-1"].avatar_url == "https://jf.example.com/Users/jf-1/Images/Primary"
        assert by_uid["jf-1"].email is None

    asyncio.run(scenario())


def test_unsupported_provider_raises_registration_error(tmp_path):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        svc = _service(store)
        with pytest.raises(RegistrationError):
            await svc.import_users("navidrome", ["x"])

    asyncio.run(scenario())


def test_unknown_uid_is_skipped_not_imported(tmp_path):
    async def scenario():
        store = AuthStore(tmp_path / "library.db")
        svc = _service(store, jellyfin=[JellyfinUser(id="jf-1", name="Alice")])

        result = await svc.import_users("jellyfin", ["does-not-exist"])

        assert result.imported == []
        assert result.skipped == ["does-not-exist"]

    asyncio.run(scenario())
