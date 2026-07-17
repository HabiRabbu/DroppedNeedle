from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from api.v1.routes.jellyfin_library import router
from core.dependencies import get_jellyfin_library_service, get_playlist_service
from core.exceptions import MediaAccountRelinkRequiredError, ResourceNotFoundError
from tests.helpers import build_test_client, override_user_auth


@pytest.fixture
def service():
    result = MagicMock()
    result.get_playlist_image = AsyncMock(
        return_value=(b"playlist-image", "image/jpeg")
    )
    return result


def _client(service, *, authenticated: bool = True, user_id: str = "user-a"):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_jellyfin_library_service] = lambda: service
    app.dependency_overrides[get_playlist_service] = lambda: MagicMock()
    if authenticated:
        override_user_auth(app, user_id=user_id)
    return build_test_client(app)


def test_playlist_image_is_private_and_passes_requesting_user(service):
    response = _client(service).get(
        "/jellyfin/playlist-image/playlist-1/item-1?size=320"
    )

    assert response.status_code == 200
    assert response.content == b"playlist-image"
    assert response.headers["cache-control"] == "private, no-store"
    call = service.get_playlist_image.await_args
    assert call.args[0:2] == ("playlist-1", "item-1")
    assert call.args[2].id == "user-a"
    assert call.args[3] == 320


def test_playlist_image_requires_authentication(service):
    response = _client(service, authenticated=False).get(
        "/jellyfin/playlist-image/playlist-1/item-1"
    )

    assert response.status_code == 401
    service.get_playlist_image.assert_not_awaited()


def test_playlist_image_hides_items_not_visible_to_requesting_user(service):
    service.get_playlist_image = AsyncMock(
        side_effect=ResourceNotFoundError("not visible")
    )

    response = _client(service, user_id="user-b").get(
        "/jellyfin/playlist-image/playlist-1/item-1"
    )

    assert response.status_code == 404


def test_stale_link_returns_actionable_relink_error_code(service):
    service.list_user_playlists = AsyncMock(
        side_effect=MediaAccountRelinkRequiredError(
            "Reconnect Jellyfin to check your playlists"
        )
    )

    response = _client(service).get("/jellyfin/playlists")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MEDIA_ACCOUNT_RELINK_REQUIRED"
