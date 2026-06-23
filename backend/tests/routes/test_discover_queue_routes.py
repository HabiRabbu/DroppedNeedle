import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.schemas.discover import DiscoverQueueResponse, DiscoverQueueItemLight
from api.v1.routes.discover import router
from core.dependencies import get_discover_service, get_discover_queue_manager
from tests.helpers import override_user_auth

_UID = "test-user-id"


def _make_queue_response(source: str) -> DiscoverQueueResponse:
    return DiscoverQueueResponse(
        items=[
            DiscoverQueueItemLight(
                release_group_mbid="rg-mbid-1",
                album_name="Test Album",
                artist_name="Test Artist",
                artist_mbid="artist-mbid-1",
                cover_url="/covers/release-group/rg-mbid-1?size=500",
                recommendation_reason=f"From {source}",
                in_library=False,
            )
        ],
        queue_id="test-queue-id",
    )


@pytest.fixture
def mock_discover_service():
    mock = AsyncMock()
    mock.build_queue = AsyncMock(return_value=_make_queue_response("listenbrainz"))
    mock.resolve_source_for_user = AsyncMock(side_effect=lambda uid, s: s or "listenbrainz")
    return mock


@pytest.fixture
def mock_queue_manager():
    mock = AsyncMock()
    mock.consume_queue = AsyncMock(return_value=None)
    mock.build_hydrated_queue = AsyncMock(return_value=_make_queue_response("listenbrainz"))
    return mock


@pytest.fixture
def client(mock_discover_service, mock_queue_manager):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_discover_service] = lambda: mock_discover_service
    app.dependency_overrides[get_discover_queue_manager] = lambda: mock_queue_manager
    override_user_auth(app, user_id=_UID)
    return TestClient(app)


class TestDiscoverQueueSourceRoute:
    def test_queue_passes_source_param_to_service(self, client, mock_discover_service):
        resp = client.get("/discover/queue?source=lastfm")
        assert resp.status_code == 200
        mock_discover_service.build_queue.assert_not_called()

    def test_queue_passes_source_param_to_manager(self, client, mock_queue_manager):
        resp = client.get("/discover/queue?source=lastfm")
        assert resp.status_code == 200
        mock_queue_manager.build_hydrated_queue.assert_awaited_once_with(_UID, "lastfm", None)

    def test_queue_passes_listenbrainz_source(self, client, mock_discover_service):
        resp = client.get("/discover/queue?source=listenbrainz")
        assert resp.status_code == 200
        mock_discover_service.build_queue.assert_not_called()

    def test_queue_no_source_uses_resolved_source(self, client, mock_discover_service, mock_queue_manager):
        resp = client.get("/discover/queue")
        assert resp.status_code == 200
        mock_queue_manager.build_hydrated_queue.assert_awaited_once_with(_UID, "listenbrainz", None)
        mock_discover_service.resolve_source_for_user.assert_awaited_once_with(_UID, None)

    def test_queue_respects_count_param(self, client, mock_queue_manager):
        resp = client.get("/discover/queue?count=5&source=lastfm")
        assert resp.status_code == 200
        mock_queue_manager.build_hydrated_queue.assert_awaited_once_with(_UID, "lastfm", 5)

    def test_queue_caps_count_at_20(self, client, mock_queue_manager):
        resp = client.get("/discover/queue?count=50")
        assert resp.status_code == 200
        mock_queue_manager.build_hydrated_queue.assert_awaited_once_with(_UID, "listenbrainz", 20)

    def test_queue_returns_items(self, client, mock_discover_service):
        resp = client.get("/discover/queue?source=lastfm")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "queue_id" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["artist_name"] == "Test Artist"


class TestQueueStatusRoute:
    def test_status_returns_ok(self, client, mock_queue_manager):
        mock_queue_manager.get_status = MagicMock(
            return_value={"status": "idle", "source": "listenbrainz"}
        )
        resp = client.get("/discover/queue/status?source=listenbrainz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["source"] == "listenbrainz"

    def test_status_defaults_source_via_resolve(self, client, mock_discover_service, mock_queue_manager):
        mock_queue_manager.get_status = MagicMock(
            return_value={"status": "idle", "source": "listenbrainz"}
        )
        resp = client.get("/discover/queue/status")
        assert resp.status_code == 200
        mock_discover_service.resolve_source_for_user.assert_awaited_once_with(_UID, None)

    def test_status_ready_includes_queue_info(self, client, mock_queue_manager):
        mock_queue_manager.get_status = MagicMock(
            return_value={
                "status": "ready",
                "source": "listenbrainz",
                "queue_id": "abc",
                "item_count": 5,
                "built_at": 1000.0,
                "stale": False,
            }
        )
        resp = client.get("/discover/queue/status?source=listenbrainz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["item_count"] == 5
        assert data["stale"] is False


class TestQueueGenerateRoute:
    def test_generate_triggers_build(self, client, mock_queue_manager):
        mock_queue_manager.start_build = AsyncMock(
            return_value={"action": "started", "status": "building", "source": "listenbrainz"}
        )
        resp = client.post(
            "/discover/queue/generate",
            json={"source": "listenbrainz", "force": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "started"
        mock_queue_manager.start_build.assert_awaited_once_with(_UID, "listenbrainz", force=False)

    def test_generate_already_building(self, client, mock_queue_manager):
        mock_queue_manager.start_build = AsyncMock(
            return_value={"action": "already_building", "status": "building", "source": "listenbrainz"}
        )
        resp = client.post(
            "/discover/queue/generate",
            json={"source": "listenbrainz", "force": False},
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "already_building"

    def test_generate_force_rebuild(self, client, mock_queue_manager):
        mock_queue_manager.start_build = AsyncMock(
            return_value={"action": "started", "status": "building", "source": "listenbrainz"}
        )
        resp = client.post(
            "/discover/queue/generate",
            json={"source": "listenbrainz", "force": True},
        )
        assert resp.status_code == 200
        mock_queue_manager.start_build.assert_awaited_once_with(_UID, "listenbrainz", force=True)

    def test_generate_defaults_source(self, client, mock_discover_service, mock_queue_manager):
        mock_queue_manager.start_build = AsyncMock(
            return_value={"action": "started", "status": "building", "source": "listenbrainz"}
        )
        resp = client.post(
            "/discover/queue/generate",
            json={"force": False},
        )
        assert resp.status_code == 200
        mock_discover_service.resolve_source_for_user.assert_awaited_once_with(_UID, None)
