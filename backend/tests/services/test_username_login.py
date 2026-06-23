"""Phase 1 (AuthMultiUser D3): username login, email-optional creation, slug/de-dup
backfill, local-provider migration, and SSO username auto-derive."""

from __future__ import annotations

import sqlite3

import pytest

from core.exceptions import AuthenticationError, RegistrationError
from infrastructure.persistence.auth_store import (
    AuthStore,
    _derive_username,
    _slugify,
    _username_base,
)
from services.auth_service import AuthService, _validate_username

PASSWORD = "correct horse battery staple"  # >= 12 chars; HIBP is stubbed below


@pytest.fixture(autouse=True)
def _no_hibp(monkeypatch):
    """Keep account creation offline: skip the Have-I-Been-Pwned network check."""
    async def _noop(_password: str) -> None:
        return None

    monkeypatch.setattr("services.auth_service._check_hibp", _noop)


def _service(tmp_path) -> tuple[AuthService, AuthStore]:
    store = AuthStore(tmp_path / "library.db")
    return AuthService(store), store


def test_slugify_preserves_charset_lowercase_done_by_caller():
    assert _slugify("Jane.Doe") == "Jane.Doe"   # dot preserved, case preserved
    assert _slugify("Jane Doe") == "Jane-Doe"    # space -> '-'
    assert _slugify("  --weird__  ") == "weird"  # trim leading/trailing separators
    assert _slugify("a@b.com".split("@")[0]) == "a"
    assert _slugify("***") == ""                 # nothing usable
    assert _slugify("") == ""


def test_username_base_prefers_email_localpart_then_display_then_user():
    assert _username_base(email="Jane.Doe@example.com", display_name="Ignored") == "Jane.Doe"
    assert _username_base(email=None, display_name="Cool Person") == "Cool-Person"
    assert _username_base(email="", display_name="") == "user"
    assert _username_base(email="@@@", display_name="!!!") == "user"


def test_validate_username_rules_and_lowercasing():
    assert _validate_username("Jane.Doe") == ("jane.doe", "Jane.Doe")
    assert _validate_username("  Bob_99-x ") == ("bob_99-x", "Bob_99-x")
    for bad in ("ab", "x" * 33, "has space", "no@symbol", "", "  "):
        with pytest.raises(RegistrationError):
            _validate_username(bad)


class _FakeStore:
    def __init__(self, taken):
        self._taken = set(taken)

    async def get_user_by_username(self, username):
        return object() if username in self._taken else None


@pytest.mark.asyncio
async def test_derive_username_dedups_with_numeric_suffix():
    assert await _derive_username(_FakeStore(set()), display_name="Jane") == ("jane", "Jane")
    assert await _derive_username(_FakeStore({"jane"}), display_name="Jane") == ("jane-2", "Jane-2")
    assert await _derive_username(
        _FakeStore({"jane", "jane-2"}), display_name="Jane"
    ) == ("jane-3", "Jane-3")


@pytest.mark.asyncio
async def test_backfill_usernames_derives_dedups_and_is_idempotent(tmp_path):
    store = AuthStore(tmp_path / "library.db")
    await store.create_user(id="1", display_name="X", role="admin", email="Jane.Doe@x.com")
    await store.create_user(id="2", display_name="Jane.Doe", role="user")  # no email

    await store.backfill_usernames()

    u1 = await store.get_user_by_id("1")
    u2 = await store.get_user_by_id("2")
    assert (u1.username, u1.username_display) == ("jane.doe", "Jane.Doe")
    assert (u2.username, u2.username_display) == ("jane.doe-2", "Jane.Doe-2")

    # Idempotent: re-running skips rows that already have a username.
    await store.backfill_usernames()
    assert (await store.get_user_by_id("1")).username == "jane.doe"
    assert (await store.get_user_by_id("2")).username == "jane.doe-2"


@pytest.mark.asyncio
async def test_migrate_local_provider_to_username_idempotent_keeps_email_link(tmp_path):
    store = AuthStore(tmp_path / "library.db")
    # Legacy local account: provider_uid == email, username backfilled.
    await store.create_user(
        id="u", display_name="Jane", role="admin", email="jane@x.com",
        username="jane", username_display="Jane",
    )
    await store.create_auth_provider(
        id="p", user_id="u", provider="local", provider_uid="jane@x.com", provider_data="{}",
    )

    await store.migrate_local_provider_to_username()

    prov = await store.get_auth_provider("local", "jane")
    assert prov is not None and prov.provider_uid == "jane"
    assert await store.get_auth_provider("local", "jane@x.com") is None

    # Idempotent re-run.
    await store.migrate_local_provider_to_username()
    assert (await store.get_auth_provider("local", "jane")).provider_uid == "jane"

    # get_user_by_email is kept for SSO account-linking.
    assert (await store.get_user_by_email("jane@x.com")).id == "u"


@pytest.mark.asyncio
async def test_create_first_admin_stores_lowercased_username_optional_email(tmp_path):
    svc, _ = _service(tmp_path)
    user, token = await svc.create_first_admin(
        display_name="Jane", username="Jane.Doe", password=PASSWORD,
    )
    assert token
    assert user.username == "jane.doe"
    assert user.username_display == "Jane.Doe"
    assert user.email is None


@pytest.mark.asyncio
async def test_login_local_mixed_case_input_and_failure_paths(tmp_path):
    svc, _ = _service(tmp_path)
    created, _ = await svc.create_first_admin(
        display_name="Jane", username="Jane.Doe", password=PASSWORD,
    )

    # Mixed-case input is lowercased before lookup.
    user, token = await svc.login_local(username="JANE.DOE", password=PASSWORD)
    assert user.id == created.id and token

    with pytest.raises(AuthenticationError):
        await svc.login_local(username="jane.doe", password="wrong-password-value")

    # Unknown username hits the dummy-verify path, no crash.
    with pytest.raises(AuthenticationError):
        await svc.login_local(username="nobody", password=PASSWORD)


@pytest.mark.asyncio
async def test_admin_create_user_optional_email_and_duplicate_username(tmp_path):
    svc, _ = _service(tmp_path)
    await svc.create_first_admin(display_name="Admin", username="admin", password=PASSWORD)

    user = await svc.admin_create_user(display_name="Jane", username="Jane", password=PASSWORD)
    assert user.username == "jane" and user.email is None

    # Duplicate username (case-insensitive) is rejected.
    with pytest.raises(RegistrationError):
        await svc.admin_create_user(display_name="Jane2", username="JANE", password=PASSWORD)


@pytest.mark.asyncio
async def test_jellyfin_new_user_autoderives_username_and_dedups(tmp_path):
    from services.jellyfin_user_auth_service import JellyfinUserAuthService

    store = AuthStore(tmp_path / "library.db")
    svc = JellyfinUserAuthService(store, None, None)

    profile = {
        "jellyfin_user_id": "jf-1", "username": "Jane Doe",
        "email": None, "thumb": None, "access_token": "tok",
    }
    user = await svc._find_or_create_user(profile)
    assert user.username == "jane-doe" and user.username_display == "Jane-Doe"

    profile2 = {**profile, "jellyfin_user_id": "jf-2", "access_token": "tok2"}
    user2 = await svc._find_or_create_user(profile2)
    assert user2.username == "jane-doe-2"


@pytest.mark.asyncio
async def test_sso_new_user_retries_on_username_index_race(tmp_path, monkeypatch):
    """A concurrent first-login that loses the username race re-derives instead of 500ing."""
    from services.jellyfin_user_auth_service import JellyfinUserAuthService

    store = AuthStore(tmp_path / "library.db")
    svc = JellyfinUserAuthService(store, None, None)

    real_create = store.create_user
    calls = {"n": 0}

    async def flaky_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.IntegrityError("UNIQUE constraint failed: idx_auth_users_username")
        return await real_create(**kwargs)

    monkeypatch.setattr(store, "create_user", flaky_create)

    profile = {
        "jellyfin_user_id": "jf-1", "username": "Jane Doe",
        "email": None, "thumb": None, "access_token": "tok",
    }
    user = await svc._find_or_create_user(profile)
    assert user.username == "jane-doe"
    assert calls["n"] >= 2  # retried after the simulated race


@pytest.mark.asyncio
async def test_plex_new_user_autoderives_username(tmp_path):
    from services.plex_user_auth_service import PlexUserAuthService

    store = AuthStore(tmp_path / "library.db")
    svc = PlexUserAuthService(store, None, None)

    profile = {
        "uuid": "plex-1", "email": "", "display_name": "Cool Person",
        "thumb": None, "auth_token": "tok",
    }
    user = await svc._find_or_create_user(profile, "tok")
    assert user.username == "cool-person" and user.username_display == "Cool-Person"


@pytest.mark.asyncio
async def test_oidc_new_user_autoderives_username(tmp_path):
    from services.oidc_user_auth_service import OIDCUserAuthService

    store = AuthStore(tmp_path / "library.db")
    svc = OIDCUserAuthService(store, None, None)

    profile = {"sub": "oidc-1", "email": None, "name": "Alice Smith", "thumb": None}
    user = await svc._find_or_create_user(profile, {"access_token": "a", "refresh_token": "r"})
    assert user.username == "alice-smith" and user.username_display == "Alice-Smith"
