"""Download search route tests: search/pick/cancel with user scope + domain-exception mapping."""

from unittest.mock import AsyncMock

from fastapi import FastAPI

from api.v1.routes import downloads_search
from core.dependencies import get_download_service
from core.exceptions import PermissionDeniedError, ValidationError
from middleware import _get_current_user
from services.native.download_service import ALREADY_IN_LIBRARY
from tests.helpers import build_test_client, mock_user


def _app(service) -> FastAPI:
    app = FastAPI()
    app.include_router(downloads_search.router)
    app.dependency_overrides[get_download_service] = lambda: service
    app.dependency_overrides[_get_current_user] = lambda: mock_user(role="user", user_id="u1")
    return app


def test_search_album_returns_job_id():
    service = AsyncMock()
    service.search_album.return_value = "job1"
    response = build_test_client(_app(service)).post(
        "/downloads/search/album", json={"artist_name": "A", "album_title": "B"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "searching", "job_id": "job1"}


def test_search_album_already_in_library():
    service = AsyncMock()
    service.search_album.return_value = ALREADY_IN_LIBRARY
    response = build_test_client(_app(service)).post(
        "/downloads/search/album",
        json={"artist_name": "A", "album_title": "B", "release_group_mbid": "rg"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "already_in_library"
    assert body["job_id"] is None


def test_search_album_unauthenticated():
    service = AsyncMock()
    app = FastAPI()
    app.include_router(downloads_search.router)
    app.dependency_overrides[get_download_service] = lambda: service
    response = build_test_client(app).post(
        "/downloads/search/album", json={"artist_name": "A", "album_title": "B"}
    )
    assert response.status_code == 401


def test_pick_success():
    service = AsyncMock()
    service.pick_candidate.return_value = "task1"
    response = build_test_client(_app(service)).post(
        "/downloads/search/job1/pick", json={"candidate_index": 0}
    )
    assert response.status_code == 200
    assert response.json()["task_id"] == "task1"


def test_pick_non_owner_forbidden():
    service = AsyncMock()
    service.pick_candidate.side_effect = PermissionDeniedError("not yours")
    response = build_test_client(_app(service)).post(
        "/downloads/search/job1/pick", json={"candidate_index": 0}
    )
    assert response.status_code == 403


def test_pick_invalid_index_400():
    service = AsyncMock()
    service.pick_candidate.side_effect = ValidationError("Invalid candidate index")
    response = build_test_client(_app(service)).post(
        "/downloads/search/job1/pick", json={"candidate_index": 99}
    )
    assert response.status_code == 400


def test_cancel_search():
    service = AsyncMock()
    service.cancel_search.return_value = True
    response = build_test_client(_app(service)).post("/downloads/search/job1/cancel")
    assert response.status_code == 200
    service.cancel_search.assert_awaited_once_with("u1", "job1")


def test_search_stream_route_precedes_job_id_param():
    # /search/stream must be registered before /search/{job_id}, or Starlette
    # captures "stream" as the job_id and the SSE endpoint becomes unreachable.
    paths = [getattr(r, "path", "") for r in downloads_search.router.routes]
    stream_i = next(i for i, p in enumerate(paths) if p.endswith("/search/stream"))
    param_i = next(i for i, p in enumerate(paths) if p.endswith("/search/{job_id}"))
    assert stream_i < param_i
