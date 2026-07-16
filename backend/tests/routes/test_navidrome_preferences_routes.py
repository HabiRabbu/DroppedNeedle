from unittest.mock import AsyncMock

from fastapi import FastAPI

from api.v1.routes.navidrome_preferences import router
from core.dependencies import get_navidrome_folder_scope_service
from infrastructure.persistence.navidrome_folder_preferences_store import (
    NavidromeFolderPreference,
)
from middleware import _get_current_user
from services.navidrome_folder_scope_service import (
    NavidromeFolderResolution,
    NavidromeFolderScope,
)
from tests.helpers import build_test_client, mock_user


def _resolution(mode="all", ids=(), *, available=True):
    preference = NavidromeFolderPreference(mode, ids, "server-1", 1.0)
    return NavidromeFolderResolution(
        preference=preference,
        scope=NavidromeFolderScope(mode, ids if mode == "selected" else ()),
        available_folders=(("a", "Folder A"), ("b", "Folder B")),
        source_available=available,
    )


def _app(service, user_id=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_navidrome_folder_scope_service] = lambda: service
    if user_id:
        app.dependency_overrides[_get_current_user] = lambda: mock_user(user_id=user_id)
    return app


def test_routes_require_authentication():
    service = AsyncMock()
    client = build_test_client(_app(service))
    path = "/me/navidrome/music-folder-preferences"
    assert client.get(path).status_code == 401
    assert client.put(path, json={"mode": "all"}).status_code == 401


def test_get_reads_only_authenticated_user():
    service = AsyncMock()
    service.resolve.return_value = _resolution("selected", ("a", "b"))
    response = build_test_client(_app(service, "alice")).get(
        "/me/navidrome/music-folder-preferences"
    )
    assert response.status_code == 200
    assert response.json()["selected_folder_ids"] == ["a", "b"]
    service.resolve.assert_awaited_once_with("alice")


def test_put_saves_only_authenticated_user():
    service = AsyncMock()
    service.save.return_value = _resolution("selected", ("a", "b"))
    response = build_test_client(_app(service, "bob")).put(
        "/me/navidrome/music-folder-preferences",
        json={"mode": "selected", "selected_folder_ids": ["b", "a"]},
    )
    assert response.status_code == 200
    service.save.assert_awaited_once_with(
        "bob", mode="selected", selected_folder_ids=["b", "a"]
    )


def test_invalid_preference_is_protocol_error():
    service = AsyncMock()
    service.save.side_effect = ValueError("Select at least one music folder")
    response = build_test_client(_app(service, "alice")).put(
        "/me/navidrome/music-folder-preferences",
        json={"mode": "selected", "selected_folder_ids": []},
    )
    assert response.status_code == 400
