"""Phase 6 (AuthMultiUser D5) route tests: the three admin import endpoints are
admin-gated, thin, force role="user" (the body cannot set role), and reject
unsupported providers. The UserImportService is faked; service behaviour is
covered by tests/services/test_user_import_service.py."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from api.v1.routes.auth import router
from core.dependencies.auth_providers import get_user_import_service
from infrastructure.persistence.auth_store import UserRecord
from middleware import _get_current_admin
from services.user_import_service import ImportCandidate, ImportResult
from tests.helpers import build_test_client, mock_admin_user, mock_user


class _StateUserMiddleware(BaseHTTPMiddleware):
    """Inject a verified user onto request.state so the real _get_current_admin
    gate runs against it (the way AuthMiddleware would)."""

    def __init__(self, app, user: UserRecord) -> None:
        super().__init__(app)
        self._user = user

    async def dispatch(self, request, call_next):
        request.state.user = self._user
        request.state.token = None
        return await call_next(request)


class _FakeImporter:
    def __init__(self) -> None:
        self.import_calls: list[tuple[str, list[str]]] = []
        self.jellyfin = [
            ImportCandidate(provider="jellyfin", provider_uid="jf-1", display_name="Alice"),
            ImportCandidate(provider="jellyfin", provider_uid="jf-2", display_name="Bob", already_imported=True),
        ]
        self.plex = [
            ImportCandidate(
                provider="plex",
                provider_uid="px-1",
                display_name="Cara",
                email="c@x.y",
                avatar_url="https://plex.tv/u/1/avatar",
            ),
        ]

    async def list_jellyfin_users(self):
        return list(self.jellyfin)

    async def list_plex_users(self):
        return list(self.plex)

    async def import_users(self, provider, provider_uids):
        self.import_calls.append((provider, list(provider_uids)))
        user = UserRecord(
            id="new-1",
            display_name="Alice",
            role="user",
            created_at="t",
            username="alice",
            username_display="Alice",
        )
        return ImportResult(imported=[user], linked=[], skipped=["jf-2"])


def _app(importer, *, admin: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_import_service] = lambda: importer
    if admin:
        app.dependency_overrides[_get_current_admin] = mock_admin_user
    else:
        app.add_middleware(_StateUserMiddleware, user=mock_user(role="user"))
    return app


def test_admin_list_jellyfin_returns_candidates():
    importer = _FakeImporter()
    client = build_test_client(_app(importer, admin=True))

    resp = client.get("/auth/admin/import/jellyfin")

    assert resp.status_code == 200
    users = resp.json()["users"]
    assert {u["provider_uid"] for u in users} == {"jf-1", "jf-2"}
    assert {u["provider_uid"] for u in users if u["already_imported"]} == {"jf-2"}


def test_admin_list_plex_returns_candidates():
    importer = _FakeImporter()
    client = build_test_client(_app(importer, admin=True))

    resp = client.get("/auth/admin/import/plex")

    assert resp.status_code == 200
    users = resp.json()["users"]
    assert users[0]["provider_uid"] == "px-1"
    assert users[0]["email"] == "c@x.y"
    assert users[0]["avatar_url"] == "https://plex.tv/u/1/avatar"


def test_admin_import_returns_counts_and_delegates_thinly():
    importer = _FakeImporter()
    client = build_test_client(_app(importer, admin=True))

    resp = client.post(
        "/auth/admin/import",
        json={"provider": "jellyfin", "provider_uids": ["jf-1", "jf-2"]},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_imported"] == 1
    assert body["imported"][0]["role"] == "user"
    assert body["skipped"] == ["jf-2"]
    assert importer.import_calls == [("jellyfin", ["jf-1", "jf-2"])]


def test_import_body_cannot_set_role():
    importer = _FakeImporter()
    client = build_test_client(_app(importer, admin=True))

    resp = client.post(
        "/auth/admin/import",
        json={"provider": "jellyfin", "provider_uids": ["jf-1"], "role": "admin"},
    )

    assert resp.status_code == 200
    assert resp.json()["imported"][0]["role"] == "user"
    # The role field is ignored and never threaded to the service.
    assert importer.import_calls == [("jellyfin", ["jf-1"])]


def test_import_unsupported_provider_rejected():
    importer = _FakeImporter()
    client = build_test_client(_app(importer, admin=True))

    resp = client.post("/auth/admin/import", json={"provider": "navidrome", "provider_uids": []})

    assert resp.status_code == 400
    assert importer.import_calls == []


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/auth/admin/import/jellyfin", None),
        ("get", "/auth/admin/import/plex", None),
        ("post", "/auth/admin/import", {"provider": "jellyfin", "provider_uids": ["jf-1"]}),
    ],
)
def test_import_endpoints_forbidden_for_non_admin(method, path, payload):
    importer = _FakeImporter()
    client = build_test_client(_app(importer, admin=False))

    resp = client.get(path) if method == "get" else client.post(path, json=payload)

    assert resp.status_code == 403
    assert importer.import_calls == []
