"""Phase 2 (AuthMultiUser D7/D8/D9) route tests for the per-user profile: self-scoped
reads/writes, self-service mutations, per-user avatar with self-or-admin authz, the
admin user-list per-user avatar path, and the shared-avatar migration. Driven through
the real profile/auth routers with a temp AuthStore + AuthService."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from api.v1.routes.auth import router as auth_router
from api.v1.routes.profile import router as profile_router
from core.dependencies import (
    get_jellyfin_library_service,
    get_local_files_service,
    get_navidrome_library_service,
    get_preferences_service,
)
from core.dependencies.auth_providers import get_auth_service
from infrastructure.persistence.auth_store import AuthStore, _derive_username
from middleware import _get_current_admin, _get_current_user
from services.auth_service import AuthService
from tests.helpers import build_test_client, mock_admin_user

PASSWORD = "correct horse battery staple"
PASSWORD2 = "another correct staple value"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def _no_hibp(monkeypatch):
    async def _noop(_password: str) -> None:
        return None

    monkeypatch.setattr("services.auth_service._check_hibp", _noop)


class _Conn:
    """A disabled shared connection - the profile aggregation stays present (D2)."""

    enabled = False
    username = ""
    user_id = ""
    jellyfin_url = ""
    navidrome_url = ""
    plex_url = ""


class _FakePrefs:
    def get_jellyfin_connection(self):
        return _Conn()

    def get_listenbrainz_connection(self):
        return _Conn()

    def get_lastfm_connection(self):
        return _Conn()

    def get_navidrome_connection(self):
        return _Conn()

    def get_plex_connection(self):
        return _Conn()


class _Stats:
    total_tracks = 0
    total_albums = 0
    total_artists = 0
    total_size_bytes = 0
    total_size_human = ""


class _FakeLocal:
    async def get_storage_stats(self):
        return _Stats()


def _build(tmp_path):
    store = AuthStore(tmp_path / "library.db")
    auth = AuthService(store)

    async def seed():
        admin = await auth.admin_create_user(display_name="Admin", username="admin", password=PASSWORD, role="admin")
        owner = await auth.admin_create_user(display_name="Owner", username="owner", password=PASSWORD, email="owner@example.com")
        other = await auth.admin_create_user(display_name="Other", username="other", password=PASSWORD)
        return admin, owner, other

    admin, owner, other = asyncio.run(seed())
    return store, auth, admin, owner, other


def _app(store: AuthStore, auth: AuthService, current_user_id: str):
    app = FastAPI()
    app.include_router(profile_router)
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_preferences_service] = lambda: _FakePrefs()
    app.dependency_overrides[get_jellyfin_library_service] = lambda: None
    app.dependency_overrides[get_local_files_service] = lambda: _FakeLocal()
    app.dependency_overrides[get_navidrome_library_service] = lambda: None

    async def _current():
        # Re-fetch each request so a mutation is reflected on the next read, the way
        # AuthMiddleware would resolve request.state.user from the token in production.
        return await store.get_user_by_id(current_user_id)

    app.dependency_overrides[_get_current_user] = _current
    return build_test_client(app)


def test_get_profile_returns_own_row(tmp_path):
    store, auth, _admin, owner, _other = _build(tmp_path)
    body = _app(store, auth, owner.id).get("/profile").json()
    assert body["display_name"] == "Owner"
    assert body["username"] == "owner"
    assert body["email"] == "owner@example.com"
    assert body["providers"] == ["local"]
    assert {s["name"] for s in body["services"]} == {"Jellyfin", "ListenBrainz", "Last.fm", "Navidrome", "Plex"}


def test_get_profile_is_self_scoped(tmp_path):
    store, auth, _admin, _owner, other = _build(tmp_path)
    body = _app(store, auth, other.id).get("/profile").json()
    assert body["username"] == "other"
    assert body["display_name"] == "Other"


def test_update_display_name_persists(tmp_path):
    store, auth, _admin, owner, _other = _build(tmp_path)
    client = _app(store, auth, owner.id)
    resp = client.put("/profile", json={"display_name": "Owner Renamed"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Owner Renamed"
    assert client.get("/profile").json()["display_name"] == "Owner Renamed"


def test_update_username_persists_and_collision_400(tmp_path):
    store, auth, _admin, owner, _other = _build(tmp_path)
    client = _app(store, auth, owner.id)

    resp = client.put("/profile/username", json={"username": "owner_new"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "owner_new"
    assert client.get("/profile").json()["username"] == "owner_new"

    collide = client.put("/profile/username", json={"username": "other"})
    assert collide.status_code == 400


def test_update_email_set_conflict_and_clear(tmp_path):
    store, auth, _admin, _owner, other = _build(tmp_path)
    client = _app(store, auth, other.id)

    assert client.put("/profile/email", json={"email": "other@example.com"}).status_code == 200
    assert client.put("/profile/email", json={"email": "owner@example.com"}).status_code == 400
    assert client.put("/profile/email", json={"email": ""}).json()["email"] is None


def test_change_password_route_status_codes(tmp_path):
    store, auth, _admin, owner, _other = _build(tmp_path)
    client = _app(store, auth, owner.id)

    assert client.post("/profile/password", json={"current_password": "wrong password here", "new_password": PASSWORD2}).status_code == 401
    assert client.post("/profile/password", json={"current_password": PASSWORD, "new_password": PASSWORD2}).status_code == 200
    assert client.post("/profile/password", json={"current_password": PASSWORD2, "new_password": "short"}).status_code == 400


def test_set_local_password_for_sso_only(tmp_path):
    store = AuthStore(tmp_path / "library.db")
    auth = AuthService(store)

    async def seed():
        username, display = await _derive_username(store, display_name="SSO User")
        user = await store.create_user(
            id="sso-1", display_name="SSO User", role="user",
            username=username, username_display=display,
        )
        await store.create_auth_provider(id="p-jf", user_id=user.id, provider="jellyfin", provider_uid="jf-1")
        return user

    user = asyncio.run(seed())
    client = _app(store, auth, user.id)

    resp = client.post("/profile/set-password", json={"new_password": PASSWORD})
    assert resp.status_code == 200
    assert "local" in resp.json()["providers"]

    # Already has a local provider now -> second attempt rejected.
    assert client.post("/profile/set-password", json={"new_password": PASSWORD2}).status_code == 400

    u, _ = asyncio.run(auth.login_local(username=user.username, password=PASSWORD))
    assert u.id == user.id


def test_avatar_upload_and_self_or_admin_authz(tmp_path):
    store, auth, admin, owner, other = _build(tmp_path)
    owner_client = _app(store, auth, owner.id)

    upload = owner_client.post("/profile/avatar", files={"file": ("a.png", PNG_BYTES, "image/png")})
    assert upload.status_code == 200
    # Per-user path with a cache-busting version suffix (D9 + avatar-refresh fix).
    assert upload.json()["avatar_url"].startswith(f"/api/v1/profile/avatar/{owner.id}?v=")

    # Self can read own avatar.
    assert owner_client.get(f"/profile/avatar/{owner.id}").status_code == 200
    # Non-admin, non-owner is refused another user's avatar (self-or-admin authz).
    assert owner_client.get(f"/profile/avatar/{other.id}").status_code == 403

    admin_client = _app(store, auth, admin.id)
    # Admin can read any user's avatar (powers the admin user list).
    assert admin_client.get(f"/profile/avatar/{owner.id}").status_code == 200
    # No avatar uploaded for `other` -> 404 even for admin.
    assert admin_client.get(f"/profile/avatar/{other.id}").status_code == 404


def test_admin_user_list_carries_per_user_avatar_path(tmp_path):
    store, auth, _admin, owner, _other = _build(tmp_path)
    asyncio.run(store.update_user_profile(owner.id, avatar_url=f"/api/v1/profile/avatar/{owner.id}"))

    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    client = build_test_client(app)

    users = {u["username"]: u for u in client.get("/auth/admin/users").json()["users"]}
    assert users["owner"]["avatar_url"] == f"/api/v1/profile/avatar/{owner.id}"


def test_migrate_shared_avatar_to_first_admin(tmp_path):
    from main import _migrate_shared_avatar_to_first_admin

    store = AuthStore(tmp_path / "library.db")
    auth = AuthService(store)

    async def seed():
        return await auth.admin_create_user(display_name="Admin", username="admin", password=PASSWORD, role="admin")

    admin = asyncio.run(seed())

    cache_dir = tmp_path / "cache"
    legacy = cache_dir / "profile"
    legacy.mkdir(parents=True)
    (legacy / "avatar.png").write_bytes(PNG_BYTES)

    asyncio.run(_migrate_shared_avatar_to_first_admin(store, cache_dir))

    assert (cache_dir / "avatars" / f"{admin.id}.png").exists()
    assert not (legacy / "avatar.png").exists()
    assert asyncio.run(store.get_user_by_id(admin.id)).avatar_url == f"/api/v1/profile/avatar/{admin.id}"

    # Idempotent: a re-run is a no-op (admin already has an avatar_url).
    asyncio.run(_migrate_shared_avatar_to_first_admin(store, cache_dir))
    assert asyncio.run(store.get_user_by_id(admin.id)).avatar_url == f"/api/v1/profile/avatar/{admin.id}"
