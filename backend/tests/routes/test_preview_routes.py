import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.discover import router
from core.dependencies import (
    get_discover_service,
    get_discover_queue_manager,
    get_preview_repository,
    get_user_section_prefs_store,
)
from repositories.deezer_models import PreviewTrack
from tests.helpers import override_user_auth


@pytest.fixture
def preview_repo():
    repo = MagicMock()
    repo.get_track_preview = AsyncMock(
        return_value=(
            PreviewTrack(
                title="Bitter Sweet Symphony",
                artist_name="The Verve",
                preview_url="https://p/1.mp3",
                duration_s=30,
            ),
            "deezer",
        )
    )
    repo.get_album_preview_tracks = AsyncMock(
        return_value=(
            [
                PreviewTrack(
                    title="Bitter Sweet Symphony",
                    artist_name="The Verve",
                    preview_url="https://p/1.mp3",
                    duration_s=30,
                    position=1,
                ),
                PreviewTrack(
                    title="Sonnet",
                    artist_name="The Verve",
                    preview_url="https://p/2.mp3",
                    duration_s=30,
                    position=2,
                ),
            ],
            "deezer",
        )
    )
    return repo


@pytest.fixture
def client(preview_repo):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_preview_repository] = lambda: preview_repo
    app.dependency_overrides[get_discover_service] = lambda: AsyncMock()
    app.dependency_overrides[get_discover_queue_manager] = lambda: AsyncMock()
    app.dependency_overrides[get_user_section_prefs_store] = lambda: AsyncMock()
    override_user_auth(app)
    return TestClient(app)


class TestTrackPreviewRoute:
    def test_returns_preview(self, client, preview_repo):
        resp = client.get("/discover/track-preview?artist=The%20Verve&track=Bitter%20Sweet%20Symphony")
        assert resp.status_code == 200
        data = resp.json()
        assert data["preview_url"] == "https://p/1.mp3"
        assert data["provider"] == "deezer"
        preview_repo.get_track_preview.assert_awaited_once_with(
            "The Verve", "Bitter Sweet Symphony"
        )

    def test_absence_is_empty_response_not_error(self, client, preview_repo):
        preview_repo.get_track_preview = AsyncMock(return_value=(None, None))
        resp = client.get("/discover/track-preview?artist=X&track=Y")
        assert resp.status_code == 200
        assert resp.json()["preview_url"] is None

    def test_missing_params_rejected(self, client):
        assert client.get("/discover/track-preview?artist=X").status_code == 422

    def test_overlong_params_truncated(self, client, preview_repo):
        long = "x" * 500
        resp = client.get(f"/discover/track-preview?artist={long}&track=Y")
        assert resp.status_code == 200
        called_artist = preview_repo.get_track_preview.await_args.args[0]
        assert len(called_artist) == 200


class TestAlbumPreviewRoute:
    def test_returns_ordered_sampler(self, client, preview_repo):
        resp = client.get("/discover/album-preview?artist=The%20Verve&album=Urban%20Hymns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "deezer"
        assert [t["position"] for t in data["tracks"]] == [1, 2]
        preview_repo.get_album_preview_tracks.assert_awaited_once_with(
            "The Verve", "Urban Hymns", limit=4
        )

    def test_count_param_caps(self, client, preview_repo):
        resp = client.get("/discover/album-preview?artist=A&album=B&count=2")
        assert resp.status_code == 200
        preview_repo.get_album_preview_tracks.assert_awaited_once_with("A", "B", limit=2)

    def test_no_match_is_empty_list(self, client, preview_repo):
        preview_repo.get_album_preview_tracks = AsyncMock(return_value=([], None))
        resp = client.get("/discover/album-preview?artist=X&album=Y")
        assert resp.status_code == 200
        assert resp.json()["tracks"] == []
