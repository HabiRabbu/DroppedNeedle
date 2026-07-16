"""Events settings routes: GET masks keys, PUT saves + clears the events
provider chain + kicks an immediate sweep (a freshly enabled feature must not
wait out the periodic loop's sleep), and the test-connection endpoints resolve
the masked sentinel to the stored key."""

from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI

from api.v1.routes import settings as settings_routes
from api.v1.schemas.settings import (
    SKIDDLE_KEY_MASK,
    TICKETMASTER_KEY_MASK,
    EventsSettings,
)
from core.dependencies import get_events_watcher_getter, get_preferences_service
from middleware import _get_current_admin
from tests.helpers import build_test_client, mock_admin_user


@pytest.fixture
def prefs() -> Mock:
    prefs = Mock()
    prefs.get_events_settings.return_value = EventsSettings(
        enabled=True,
        ticketmaster_enabled=True,
        ticketmaster_api_key=TICKETMASTER_KEY_MASK,
    )
    prefs.get_events_settings_raw.return_value = EventsSettings(
        enabled=True,
        ticketmaster_enabled=True,
        ticketmaster_api_key="real-key",
    )
    return prefs


@pytest.fixture
def client(prefs: Mock, watcher_getter: Mock):
    app = FastAPI()
    app.include_router(settings_routes.router)
    app.dependency_overrides[get_preferences_service] = lambda: prefs
    app.dependency_overrides[get_events_watcher_getter] = lambda: watcher_getter
    app.dependency_overrides[_get_current_admin] = mock_admin_user
    return build_test_client(app)


def test_get_returns_masked_settings(client, prefs):
    response = client.get("/settings/events")
    assert response.status_code == 200
    assert response.json()["ticketmaster_api_key"] == TICKETMASTER_KEY_MASK
    prefs.get_events_settings_raw.assert_not_called()  # masked getter only


@pytest.fixture
def watcher_getter() -> Mock:
    return Mock()


def test_put_saves_clears_cache_and_kicks_a_sweep(client, prefs, watcher_getter):
    with (
        patch("core.tasks.kick_events_sweep") as kick,
        patch.object(settings_routes, "_clear_events_cache") as clear,
    ):
        response = client.put(
            "/settings/events",
            json={
                "enabled": True,
                "ticketmaster_enabled": True,
                "ticketmaster_api_key": "k",
            },
        )
    assert response.status_code == 200
    prefs.save_events_settings.assert_called_once()
    clear.assert_called_once()
    kick.assert_called_once_with(watcher_getter)


def test_put_rejects_malformed_poll_time(client, prefs):
    response = client.put(
        "/settings/events",
        json={"enabled": True, "poll_time": "25:99"},
    )
    assert response.status_code == 422
    prefs.save_events_settings.assert_not_called()


def test_put_rejects_unknown_sweep_scope(client, prefs):
    response = client.put(
        "/settings/events",
        json={"enabled": True, "sweep_scope": "everything"},
    )
    assert response.status_code == 422
    prefs.save_events_settings.assert_not_called()


def test_test_ticketmaster_resolves_masked_key_to_stored(client, prefs):
    with patch(
        "repositories.ticketmaster_repository.TicketmasterRepository.test_connection"
    ) as test_connection:

        async def _ok():
            return True

        test_connection.side_effect = _ok
        response = client.post(
            "/settings/events/test-ticketmaster",
            json={"ticketmaster_api_key": TICKETMASTER_KEY_MASK},
        )
    assert response.status_code == 200
    assert response.json()["valid"] is True
    prefs.get_events_settings_raw.assert_called_once()  # mask resolved to stored


def test_test_ticketmaster_without_any_key_is_invalid(client, prefs):
    prefs.get_events_settings_raw.return_value = EventsSettings()
    response = client.post(
        "/settings/events/test-ticketmaster",
        json={"ticketmaster_api_key": TICKETMASTER_KEY_MASK},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_test_skiddle_resolves_masked_key_to_stored(client, prefs):
    prefs.get_events_settings_raw.return_value = EventsSettings(
        enabled=True, skiddle_enabled=True, skiddle_api_key="real-sk-key"
    )
    with patch(
        "repositories.skiddle_repository.SkiddleRepository.test_connection"
    ) as test_connection:

        async def _ok():
            return True

        test_connection.side_effect = _ok
        response = client.post(
            "/settings/events/test-skiddle",
            json={"skiddle_api_key": SKIDDLE_KEY_MASK},
        )
    assert response.status_code == 200
    assert response.json()["valid"] is True
    prefs.get_events_settings_raw.assert_called_once()


def test_test_skiddle_without_any_key_is_invalid(client, prefs):
    prefs.get_events_settings_raw.return_value = EventsSettings()
    response = client.post(
        "/settings/events/test-skiddle",
        json={"skiddle_api_key": SKIDDLE_KEY_MASK},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
