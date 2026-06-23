"""Phase 2 (AuthMultiUser D8) service-level self-service tests: change own
username/email/password and set a local password on an SSO-only account, driven
through a real AuthService + temp AuthStore."""

from __future__ import annotations

import asyncio

import pytest

from core.exceptions import AuthenticationError, RegistrationError
from infrastructure.persistence.auth_store import AuthStore, _derive_username
from services.auth_service import AuthService

PASSWORD = "correct horse battery staple"
PASSWORD2 = "another correct staple value"


@pytest.fixture(autouse=True)
def _no_hibp(monkeypatch):
    async def _noop(_password: str) -> None:
        return None

    monkeypatch.setattr("services.auth_service._check_hibp", _noop)


def _setup(tmp_path) -> tuple[AuthStore, AuthService]:
    store = AuthStore(tmp_path / "library.db")
    return store, AuthService(store)


def test_rename_syncs_local_provider_uid(tmp_path):
    """M3 fix: after a rename, login resolves by the NEW username, not the old one."""
    async def scenario():
        store, auth = _setup(tmp_path)
        user = await auth.admin_create_user(display_name="Alice", username="alice", password=PASSWORD)

        renamed = await auth.update_username(user.id, "Alice2")
        assert renamed.username == "alice2"
        assert renamed.username_display == "Alice2"

        u, _ = await auth.login_local(username="alice2", password=PASSWORD)
        assert u.id == user.id

        with pytest.raises(AuthenticationError):
            await auth.login_local(username="alice", password=PASSWORD)

    asyncio.run(scenario())


def test_update_username_collision_raises(tmp_path):
    async def scenario():
        _store, auth = _setup(tmp_path)
        await auth.admin_create_user(display_name="Alice", username="alice", password=PASSWORD)
        bob = await auth.admin_create_user(display_name="Bob", username="bob", password=PASSWORD)
        with pytest.raises(RegistrationError):
            await auth.update_username(bob.id, "alice")

    asyncio.run(scenario())


def test_change_password_flow(tmp_path):
    async def scenario():
        _store, auth = _setup(tmp_path)
        user = await auth.admin_create_user(display_name="Cara", username="cara", password=PASSWORD)

        with pytest.raises(AuthenticationError):
            await auth.change_password(user.id, "wrong password here", PASSWORD2)

        await auth.change_password(user.id, PASSWORD, PASSWORD2)
        u, _ = await auth.login_local(username="cara", password=PASSWORD2)
        assert u.id == user.id
        with pytest.raises(AuthenticationError):
            await auth.login_local(username="cara", password=PASSWORD)

        with pytest.raises(RegistrationError):
            await auth.change_password(user.id, PASSWORD2, "short")

    asyncio.run(scenario())


def test_set_local_password_for_sso_only_account(tmp_path):
    async def scenario():
        store, auth = _setup(tmp_path)
        username, display = await _derive_username(store, display_name="SSO User")
        user = await store.create_user(
            id="sso-1", display_name="SSO User", role="user",
            username=username, username_display=display,
        )
        await store.create_auth_provider(
            id="p-jf", user_id=user.id, provider="jellyfin", provider_uid="jf-123",
        )

        await auth.set_local_password(user.id, PASSWORD)

        providers = await store.list_providers_for_user(user.id)
        local = next(p for p in providers if p.provider == "local")
        assert local.provider_uid == username

        u, _ = await auth.login_local(username=username, password=PASSWORD)
        assert u.id == user.id

        # Second call now finds an existing local provider -> rejected.
        with pytest.raises(RegistrationError):
            await auth.set_local_password(user.id, PASSWORD2)

    asyncio.run(scenario())


def test_set_local_password_rejected_when_local_exists(tmp_path):
    async def scenario():
        _store, auth = _setup(tmp_path)
        user = await auth.admin_create_user(display_name="Local", username="localu", password=PASSWORD)
        with pytest.raises(RegistrationError):
            await auth.set_local_password(user.id, PASSWORD2)

    asyncio.run(scenario())


def test_update_email_set_conflict_and_clear(tmp_path):
    async def scenario():
        _store, auth = _setup(tmp_path)
        await auth.admin_create_user(
            display_name="A", username="usera", password=PASSWORD, email="a@example.com",
        )
        b = await auth.admin_create_user(display_name="B", username="userb", password=PASSWORD)

        updated = await auth.update_email(b.id, "b@example.com")
        assert updated.email == "b@example.com"

        # Case-insensitive dedupe against another user's email.
        with pytest.raises(RegistrationError):
            await auth.update_email(b.id, "A@Example.com")

        cleared = await auth.update_email(b.id, "")
        assert cleared.email is None

    asyncio.run(scenario())
