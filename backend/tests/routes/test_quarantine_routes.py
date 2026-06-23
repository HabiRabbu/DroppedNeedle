"""Quarantine route tests: admin-only list (paginated) + delete."""

from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException

from api.v1.routes import quarantine
from core.dependencies import get_download_store
from middleware import _get_current_admin
from tests.helpers import build_test_client, mock_admin_user


def _store():
    store = AsyncMock()
    store.list_quarantine.return_value = [
        {
            "id": 1,
            "client_id": "slskd",
            "username": "peerX",
            "filename": "bad.flac",
            "reason": "verify_failed",
            "quarantined_at": 1.0,
            "release_group_mbid": None,
        }
    ]
    return store


def _app(store) -> FastAPI:
    app = FastAPI()
    app.include_router(quarantine.router)
    app.dependency_overrides[get_download_store] = lambda: store
    return app


def _deny_admin():
    raise HTTPException(status_code=403, detail="admin only")


def test_list_quarantine_admin():
    app = _app(_store())
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    response = build_test_client(app).get("/downloads/quarantine")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["items"][0]["filename"] == "bad.flac"


def test_list_quarantine_non_admin_forbidden():
    app = _app(_store())
    app.dependency_overrides[_get_current_admin] = _deny_admin
    assert build_test_client(app).get("/downloads/quarantine").status_code == 403


def test_list_quarantine_unauthenticated():
    app = _app(_store())
    assert build_test_client(app).get("/downloads/quarantine").status_code == 401


def test_delete_quarantine_admin():
    store = _store()
    app = _app(store)
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    response = build_test_client(app).delete("/downloads/quarantine/5")
    assert response.status_code == 200
    assert response.json()["success"] is True
    store.delete_quarantine.assert_awaited_once_with(5)
