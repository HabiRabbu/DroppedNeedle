"""GET /discover must surface the build-time service_status the cached copy carries,
merging any in-request degradations over it (issue #147)."""

import pytest
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.discover import router
from api.v1.schemas.discover import DiscoverResponse
from core.dependencies import get_discover_service, get_user_section_prefs_store
from infrastructure.degradation import get_degradation_context
from infrastructure.integration_result import IntegrationResult
from middleware import DegradationMiddleware
from tests.helpers import override_user_auth

_UID = "test-user-id"


@pytest.fixture
def mock_discover_service():
    mock = AsyncMock()
    mock.get_discover_data = AsyncMock(
        return_value=DiscoverResponse(service_status={"listenbrainz": "degraded"})
    )
    return mock


@pytest.fixture
def mock_section_prefs():
    mock = AsyncMock()
    mock.get_disabled = AsyncMock(return_value=set())
    return mock


@pytest.fixture
def client(mock_discover_service, mock_section_prefs):
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(DegradationMiddleware)
    app.dependency_overrides[get_discover_service] = lambda: mock_discover_service
    app.dependency_overrides[get_user_section_prefs_store] = lambda: mock_section_prefs
    override_user_auth(app, user_id=_UID)
    return TestClient(app)


def test_cached_build_status_passes_through(client):
    resp = client.get("/discover")
    assert resp.status_code == 200
    assert resp.json()["service_status"] == {"listenbrainz": "degraded"}


def test_in_request_degradation_merges_over_cached_status(client, mock_discover_service):
    async def _get(user_id):
        get_degradation_context().record(
            IntegrationResult(source="musicbrainz", status="error", data=None)
        )
        return DiscoverResponse(service_status={"listenbrainz": "degraded"})

    mock_discover_service.get_discover_data = AsyncMock(side_effect=_get)
    resp = client.get("/discover")
    assert resp.status_code == 200
    assert resp.json()["service_status"] == {
        "listenbrainz": "degraded",
        "musicbrainz": "error",
    }
