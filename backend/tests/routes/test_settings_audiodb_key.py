"""Route-level tests for PUT /api/settings/advanced — AudioDB API key merge."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.schemas.advanced_settings import (
    AdvancedSettings,
    AdvancedSettingsFrontend,
    _mask_api_key,
)
from api.v1.routes.settings import router
from core.dependencies import get_preferences_service, get_settings_service
from tests.helpers import override_admin_auth


def _stored_backend(api_key: str = "originalsecret") -> AdvancedSettings:
    return AdvancedSettings(audiodb_api_key=api_key)


@pytest.fixture
def mock_prefs():
    mock = MagicMock()
    mock.get_advanced_settings.return_value = _stored_backend("originalsecret")
    mock.save_advanced_settings = MagicMock()
    return mock


@pytest.fixture
def mock_settings_service():
    mock = MagicMock()
    mock.on_coverart_settings_changed = AsyncMock()
    return mock


@pytest.fixture
def client(mock_prefs, mock_settings_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_preferences_service] = lambda: mock_prefs
    app.dependency_overrides[get_settings_service] = lambda: mock_settings_service
    override_admin_auth(app)
    yield TestClient(app)


def _default_frontend_payload(**overrides) -> dict:
    base = AdvancedSettingsFrontend()
    data = {f: getattr(base, f) for f in base.__struct_fields__}
    data.update(overrides)
    return data


class TestPutAdvancedSettingsApiKeyMerge:
    def test_masked_key_preserves_stored_key(self, client, mock_prefs):
        masked = _mask_api_key("originalsecret")
        payload = _default_frontend_payload(audiodb_api_key=masked)

        response = client.put("/settings/advanced", json=payload)

        assert response.status_code == 200
        saved = mock_prefs.save_advanced_settings.call_args[0][0]
        assert saved.audiodb_api_key == "originalsecret"

    def test_new_plaintext_key_is_saved(self, client, mock_prefs):
        payload = _default_frontend_payload(audiodb_api_key="newkey456")

        response = client.put("/settings/advanced", json=payload)

        assert response.status_code == 200
        saved = mock_prefs.save_advanced_settings.call_args[0][0]
        assert saved.audiodb_api_key == "newkey456"

    def test_short_masked_key_preserves_stored_key(self, client, mock_prefs):
        payload = _default_frontend_payload(audiodb_api_key="***")

        response = client.put("/settings/advanced", json=payload)

        assert response.status_code == 200
        saved = mock_prefs.save_advanced_settings.call_args[0][0]
        assert saved.audiodb_api_key == "originalsecret"

    def test_response_contains_masked_key_not_plaintext(self, client, mock_prefs):
        payload = _default_frontend_payload(audiodb_api_key="newkey456")
        mock_prefs.get_advanced_settings.return_value = _stored_backend("newkey456")

        response = client.put("/settings/advanced", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["audiodb_api_key"] == _mask_api_key("newkey456")
        assert "newkey456" not in data["audiodb_api_key"]

    def test_response_after_masked_submit_returns_masked(self, client, mock_prefs):
        masked = _mask_api_key("originalsecret")
        payload = _default_frontend_payload(audiodb_api_key=masked)

        response = client.put("/settings/advanced", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["audiodb_api_key"] == _mask_api_key("originalsecret")

    def test_response_reflects_backend_normalization(self, client, mock_prefs):
        """Empty key is coerced to '123' by __post_init__, response should reflect that."""
        mock_prefs.get_advanced_settings.return_value = _stored_backend("123")
        payload = _default_frontend_payload(audiodb_api_key="")

        response = client.put("/settings/advanced", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["audiodb_api_key"] == _mask_api_key("123")
