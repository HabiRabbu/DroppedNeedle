"""Security: the slskd ``api_key`` is masked at the HTTP boundary, never round-tripped.

These drive the real ``download-client`` routes against a real ``PreferencesService``
(the route unit tests mock prefs; this asserts the end-to-end masking contract):
GET masks the stored key, PUT with the masked sentinel preserves the existing key,
PUT with a new value updates it, and the plaintext key is never serialised.
"""

from pathlib import Path

from fastapi import FastAPI

from api.v1.routes import download_client
from api.v1.schemas.settings import DOWNLOAD_CLIENT_API_KEY_MASK, DownloadClientConnectionSettings
from core.config import Settings
from core.dependencies import get_preferences_service
from middleware import _get_current_admin
from services.preferences_service import PreferencesService
from tests.helpers import build_test_client, mock_admin_user

_REAL_KEY = "real-secret-key-do-not-leak"


def _prefs(tmp_path: Path) -> PreferencesService:
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    return PreferencesService(settings)


def _app(prefs: PreferencesService) -> FastAPI:
    app = FastAPI()
    app.include_router(download_client.router)
    app.dependency_overrides[get_preferences_service] = lambda: prefs
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    return app


def _put_body(**overrides) -> dict:
    body = {
        "enabled": True,
        "client_type": "slskd",
        "url": "http://slskd:5030",
        "api_key": _REAL_KEY,
    }
    body.update(overrides)
    return body


def test_get_config_masks_api_key(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.save_download_client_settings(
        DownloadClientConnectionSettings(url="http://slskd:5030", api_key=_REAL_KEY)
    )
    response = build_test_client(_app(prefs)).get("/download-client/config")
    assert response.status_code == 200
    assert response.json()["api_key"] == DOWNLOAD_CLIENT_API_KEY_MASK
    assert _REAL_KEY not in response.text


def test_put_with_mask_preserves_existing_key(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.save_download_client_settings(
        DownloadClientConnectionSettings(url="http://slskd:5030", api_key=_REAL_KEY)
    )
    response = build_test_client(_app(prefs)).put(
        "/download-client/config",
        json=_put_body(api_key=DOWNLOAD_CLIENT_API_KEY_MASK, url="http://new:5030"),
    )
    assert response.status_code == 200
    raw = prefs.get_download_client_settings_raw()
    assert raw.api_key == _REAL_KEY  # masked sentinel preserved the stored key
    assert raw.url == "http://new:5030"  # other fields still updated


def test_put_with_new_value_updates_key(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.save_download_client_settings(
        DownloadClientConnectionSettings(url="http://slskd:5030", api_key="old-key")
    )
    client = build_test_client(_app(prefs))
    response = client.put("/download-client/config", json=_put_body(api_key="brand-new-key"))
    assert response.status_code == 200
    assert prefs.get_download_client_settings_raw().api_key == "brand-new-key"
    # the freshly-set key is still masked when read back over the wire
    assert client.get("/download-client/config").json()["api_key"] == DOWNLOAD_CLIENT_API_KEY_MASK


# --- Newznab indexer keys (D6/D12) - the per-array-element masking case ----------

def _indexer_app(prefs: PreferencesService) -> FastAPI:
    from api.v1.routes import indexers

    app = FastAPI()
    app.include_router(indexers.router)
    app.dependency_overrides[get_preferences_service] = lambda: prefs
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    return app


def test_indexer_list_masks_key_and_never_leaks_plaintext(tmp_path):
    from api.v1.schemas.settings import INDEXER_API_KEY_MASK, NewznabIndexerSettings

    prefs = _prefs(tmp_path)
    prefs.save_indexer(
        NewznabIndexerSettings(name="DS", url="https://idx.test/api", api_key=_REAL_KEY)
    )
    response = build_test_client(_indexer_app(prefs)).get("/indexers")
    assert response.status_code == 200
    assert response.json()[0]["api_key"] == INDEXER_API_KEY_MASK
    assert _REAL_KEY not in response.text


def test_indexer_create_over_wire_encrypts_and_masks(tmp_path):
    from api.v1.schemas.settings import INDEXER_API_KEY_MASK

    prefs = _prefs(tmp_path)
    client = build_test_client(_indexer_app(prefs))
    created = client.post(
        "/indexers", json={"name": "DS", "url": "https://idx.test/api", "api_key": _REAL_KEY}
    )
    assert created.status_code == 200
    # stored encrypted (the raw decrypt yields the real key, but the wire shows the mask)
    raw = prefs.get_indexers_raw()[0]
    assert raw.api_key == _REAL_KEY
    listed = client.get("/indexers")
    assert listed.json()[0]["api_key"] == INDEXER_API_KEY_MASK
    assert _REAL_KEY not in listed.text
