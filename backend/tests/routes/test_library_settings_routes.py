"""Route tests for /settings/library (admin-gated; AcoustID key masked)."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from api.v1.routes.settings import router
from api.v1.schemas.settings import ACOUSTID_KEY_MASK, LibrarySettings
from core.dependencies import get_preferences_service
from tests.helpers import build_test_client, override_admin_auth


@pytest.fixture
def mock_prefs():
    prefs = MagicMock()
    prefs.get_library_settings.return_value = LibrarySettings(
        library_paths=["/music"], acoustid_api_key=ACOUSTID_KEY_MASK
    )
    prefs.get_library_settings_raw.return_value = LibrarySettings(
        library_paths=["/music"], acoustid_api_key="real-key"
    )
    prefs.save_library_settings = MagicMock()
    return prefs


@pytest.fixture
def client(mock_prefs):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_preferences_service] = lambda: mock_prefs
    override_admin_auth(app)
    return build_test_client(app)


def test_get_library_settings_masks_key(client):
    resp = client.get("/settings/library")
    assert resp.status_code == 200
    body = resp.json()
    assert body["library_paths"] == ["/music"]
    assert body["acoustid_api_key"] == ACOUSTID_KEY_MASK


def test_put_library_settings_saves(client, mock_prefs):
    resp = client.put(
        "/settings/library",
        json={
            "library_paths": ["/m2"],
            "staging_path": "/staging",
            "naming_template": "{title}.{ext}",
            "acoustid_api_key": ACOUSTID_KEY_MASK,
        },
    )
    assert resp.status_code == 200
    mock_prefs.save_library_settings.assert_called_once()


def test_add_library_path(client, mock_prefs, tmp_path):
    # path is validated at add-time, so it must be a real directory
    resp = client.post("/settings/library/paths", json={"path": str(tmp_path)})
    assert resp.status_code == 200
    saved = mock_prefs.save_library_settings.call_args.args[0]
    assert str(tmp_path) in saved.library_paths
    assert saved.acoustid_api_key == ACOUSTID_KEY_MASK  # preserved, never re-encrypted raw


def test_add_library_path_rejects_missing_directory(client, mock_prefs, tmp_path):
    # a typo'd/unmounted path must fail loudly, not save silently and yield an empty scan
    missing = tmp_path / "does-not-exist"
    resp = client.post("/settings/library/paths", json={"path": str(missing)})
    assert resp.status_code == 400
    mock_prefs.save_library_settings.assert_not_called()


def test_add_library_path_rejects_blank(client, mock_prefs):
    resp = client.post("/settings/library/paths", json={"path": "   "})
    assert resp.status_code == 400
    mock_prefs.save_library_settings.assert_not_called()


def test_remove_library_path(client, mock_prefs):
    resp = client.delete("/settings/library/paths", params={"path": "/music"})
    assert resp.status_code == 200
    saved = mock_prefs.save_library_settings.call_args.args[0]
    assert "/music" not in saved.library_paths
