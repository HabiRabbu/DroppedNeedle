"""Download-clients (SABnzbd) + policy route tests: admin auth, masked key, the
SABnzbd Test reporting version/categories."""

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, HTTPException

from api.v1.routes import download_clients
from api.v1.schemas.settings import (
    SABNZBD_API_KEY_MASK,
    DownloadPolicySettings,
    SabnzbdConnectionSettings,
)
from core.dependencies import get_preferences_service
from middleware import _get_current_admin
from models.common import ServiceStatus
from tests.helpers import build_test_client, mock_admin_user


def _prefs():
    prefs = MagicMock()
    prefs.get_sabnzbd_connection.return_value = SabnzbdConnectionSettings(
        enabled=True, url="http://sab:8080", api_key=SABNZBD_API_KEY_MASK
    )
    prefs.get_sabnzbd_connection_raw.return_value = SabnzbdConnectionSettings(
        enabled=True, url="http://sab:8080", api_key="real-key"
    )
    prefs.get_download_policy.return_value = DownloadPolicySettings()
    prefs.save_sabnzbd_connection.return_value = None
    prefs.save_download_policy.return_value = None
    return prefs


def _app(prefs=None) -> FastAPI:
    app = FastAPI()
    app.include_router(download_clients.router)
    app.dependency_overrides[get_preferences_service] = lambda: prefs or _prefs()
    return app


def _deny_admin():
    raise HTTPException(status_code=403, detail="admin only")


def test_get_sabnzbd_admin_masked():
    app = _app()
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    resp = build_test_client(app).get("/download-clients/sabnzbd")
    assert resp.status_code == 200
    assert resp.json()["api_key"] == SABNZBD_API_KEY_MASK


def test_get_sabnzbd_non_admin_forbidden():
    app = _app()
    app.dependency_overrides[_get_current_admin] = _deny_admin
    assert build_test_client(app).get("/download-clients/sabnzbd").status_code == 403


def test_get_policy_admin():
    app = _app()
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    resp = build_test_client(app).get("/download-clients/policy")
    assert resp.status_code == 200
    assert resp.json()["preflight_score_auto_accept"] == 0.70


def test_test_sabnzbd_reports_version_and_categories(monkeypatch):
    fake_client = MagicMock()
    fake_client.health_check = AsyncMock(return_value=ServiceStatus(status="ok", version="5.0.4"))
    fake_client.get_categories = AsyncMock(return_value=["*", "audio"])
    fake_client.get_complete_dir = AsyncMock(return_value="/data/Downloads/complete")
    monkeypatch.setattr(download_clients, "build_sabnzbd_download_client", lambda url, key: fake_client)

    app = _app()
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    resp = build_test_client(app).post(
        "/download-clients/sabnzbd/test", json={"url": "http://sab:8080", "api_key": "k"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["version"] == "5.0.4"
    assert "audio" in body["categories"]
    assert body["complete_dir"] == "/data/Downloads/complete"
