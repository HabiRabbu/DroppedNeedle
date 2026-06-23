"""Route-level tests for POST /api/v1/discover/playlist-suggestions."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.v1.schemas.discover import (
    PlaylistProfile,
    PlaylistSuggestionsResponse,
)
from api.v1.schemas.home import HomeAlbum, HomeSection
from api.v1.routes.discover import router
from core.dependencies import get_discover_service
from tests.helpers import override_user_auth


def _make_suggestions_response(
    playlist_id: str = "pl-1",
    source: str = "listenbrainz",
    count: int = 3,
) -> PlaylistSuggestionsResponse:
    section = HomeSection(
        title="Suggestions for your playlist",
        type="albums",
        items=[
            HomeAlbum(
                name=f"Album {i}",
                mbid=f"rg-mbid-{i}",
                artist_name="Test Artist",
                artist_mbid="artist-mbid-1",
                image_url=f"/api/v1/covers/release-group/rg-mbid-{i}?size=500",
            )
            for i in range(count)
        ],
        source=source,
    )
    return PlaylistSuggestionsResponse(
        suggestions=section,
        playlist_id=playlist_id,
        profile=PlaylistProfile(
            artist_mbids=["artist-mbid-1"],
            track_count=10,
        ),
    )


@pytest.fixture
def mock_discover_service():
    mock = AsyncMock()
    mock.get_playlist_suggestions = AsyncMock(
        return_value=_make_suggestions_response(),
    )
    mock.resolve_source = MagicMock(side_effect=lambda s: s or "listenbrainz")
    return mock


@pytest.fixture
def client(mock_discover_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_discover_service] = lambda: mock_discover_service
    override_user_auth(app)
    return TestClient(app)


class TestPostPlaylistSuggestionsValidReturns200:
    def test_returns_200(self, client, mock_discover_service) -> None:
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"playlist_id": "pl-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "suggestions" in data
        assert "playlist_id" in data
        assert "profile" in data
        assert data["playlist_id"] == "pl-1"


class TestPostPlaylistSuggestionsWithCountReturns200:
    def test_returns_200_with_count(self, client, mock_discover_service) -> None:
        mock_discover_service.get_playlist_suggestions = AsyncMock(
            return_value=_make_suggestions_response(count=5),
        )
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"playlist_id": "pl-1", "count": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["suggestions"]["items"]) == 5


class TestPostPlaylistSuggestionsWithSourceReturns200:
    def test_returns_200_with_source(self, client, mock_discover_service) -> None:
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"playlist_id": "pl-1", "source": "listenbrainz"},
        )
        assert resp.status_code == 200


class TestPostPlaylistSuggestionsInvalidSourceReturns422:
    def test_returns_422(self, client) -> None:
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"playlist_id": "pl-1", "source": "invalid"},
        )
        assert resp.status_code == 422


class TestPostPlaylistSuggestionsUnknownPlaylistReturns404:
    def test_returns_404(self, client, mock_discover_service) -> None:
        mock_discover_service.get_playlist_suggestions = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Playlist not found"),
        )
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"playlist_id": "unknown"},
        )
        assert resp.status_code == 404


class TestPostPlaylistSuggestionsEmptyProfileReturns422:
    def test_returns_422(self, client, mock_discover_service) -> None:
        mock_discover_service.get_playlist_suggestions = AsyncMock(
            side_effect=HTTPException(
                status_code=422,
                detail="Playlist has no artist data for discovery",
            ),
        )
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"playlist_id": "pl-empty"},
        )
        assert resp.status_code == 422


class TestPostPlaylistSuggestionsMissingPlaylistIdReturns422:
    def test_returns_422(self, client) -> None:
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"count": 5},
        )
        assert resp.status_code == 422


class TestPostPlaylistSuggestionsEmptyPlaylistIdReturns404:
    def test_returns_404(self, client, mock_discover_service) -> None:
        mock_discover_service.get_playlist_suggestions = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Playlist not found"),
        )
        resp = client.post(
            "/discover/playlist-suggestions",
            json={"playlist_id": ""},
        )
        assert resp.status_code == 404
