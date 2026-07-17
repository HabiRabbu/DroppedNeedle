from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.plex_library import router as plex_library_router
from api.v1.routes.stream import router as stream_router
from api.v1.schemas.plex import (
    PlexAlbumDetail,
    PlexAlbumMatch,
    PlexAlbumSummary,
    PlexArtistSummary,
    PlexLibraryStats,
    PlexSearchResponse,
    PlexTrackInfo,
)
from core.dependencies import get_plex_library_service, get_plex_playback_service, get_plex_repository
from core.exceptions import ExternalServiceError
from tests.helpers import override_user_auth


def _album_summary(id: str = "100", name: str = "Album") -> PlexAlbumSummary:
    return PlexAlbumSummary(plex_id=id, name=name, artist_name="Artist")


def _track_info(id: str = "200", title: str = "Track") -> PlexTrackInfo:
    return PlexTrackInfo(
        plex_id=id, title=title, track_number=1, disc_number=1,
        duration_seconds=200.0, part_key="/library/parts/200/file.flac",
    )


def _artist_summary(id: str = "50", name: str = "Artist") -> PlexArtistSummary:
    return PlexArtistSummary(plex_id=id, name=name)


@pytest.fixture
def mock_library_service():
    mock = MagicMock()
    mock.get_albums = AsyncMock(return_value=([_album_summary()], 42))
    mock.get_album_detail = AsyncMock(return_value=PlexAlbumDetail(
        plex_id="100", name="Album", tracks=[_track_info()],
    ))
    mock.get_artists = AsyncMock(return_value=[_artist_summary()])
    mock.search = AsyncMock(return_value=PlexSearchResponse(
        albums=[_album_summary()], artists=[_artist_summary()], tracks=[_track_info()],
    ))
    mock.get_recent = AsyncMock(return_value=[_album_summary()])
    mock.get_genres = AsyncMock(return_value=["Rock", "Jazz"])
    mock.get_stats = AsyncMock(return_value=PlexLibraryStats(
        total_tracks=100, total_albums=10, total_artists=5,
    ))
    mock.get_album_match = AsyncMock(return_value=PlexAlbumMatch(found=True, plex_album_id="100"))
    mock.get_playlist_image = AsyncMock(return_value=(b"playlist-image", "image/jpeg"))
    return mock


@pytest.fixture
def mock_repo():
    mock = MagicMock()
    mock.proxy_thumb = AsyncMock(return_value=(b"\x89PNG", "image/png"))
    return mock


@pytest.fixture
def mock_playback_service():
    mock = MagicMock()
    mock.scrobble = AsyncMock(return_value=True)
    mock.report_now_playing = AsyncMock(return_value=True)
    mock.proxy_head = AsyncMock(return_value=MagicMock(status_code=200))
    mock.proxy_stream = AsyncMock(return_value=MagicMock())
    return mock


@pytest.fixture
def library_client(mock_library_service, mock_repo):
    app = FastAPI()
    app.include_router(plex_library_router)
    app.dependency_overrides[get_plex_library_service] = lambda: mock_library_service
    app.dependency_overrides[get_plex_repository] = lambda: mock_repo
    override_user_auth(app)
    return TestClient(app)


@pytest.fixture
def stream_client(mock_playback_service):
    app = FastAPI()
    app.include_router(stream_router)
    app.dependency_overrides[get_plex_playback_service] = lambda: mock_playback_service
    override_user_auth(app)
    return TestClient(app)


class TestPlexAlbums:
    def test_get_albums(self, library_client):
        resp = library_client.get("/plex/albums")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["plex_id"] == "100"
        assert data["total"] == 42

    def test_get_albums_with_sort(self, library_client, mock_library_service):
        resp = library_client.get("/plex/albums?sort_by=year&sort_order=desc")
        assert resp.status_code == 200
        call_kwargs = mock_library_service.get_albums.call_args
        assert "year:desc" in str(call_kwargs)

    def test_get_albums_with_genre(self, library_client, mock_library_service):
        resp = library_client.get("/plex/albums?genre=Rock")
        assert resp.status_code == 200
        call_kwargs = mock_library_service.get_albums.call_args
        assert call_kwargs.kwargs.get("genre") == "Rock" or "Rock" in str(call_kwargs)

    def test_get_albums_502_on_external_error(self, library_client, mock_library_service):
        mock_library_service.get_albums = AsyncMock(side_effect=ExternalServiceError("down"))
        resp = library_client.get("/plex/albums")
        assert resp.status_code == 502

    def test_get_album_detail(self, library_client):
        resp = library_client.get("/plex/albums/100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Album"
        assert len(data["tracks"]) == 1

    def test_get_album_detail_not_found(self, library_client, mock_library_service):
        mock_library_service.get_album_detail = AsyncMock(return_value=None)
        resp = library_client.get("/plex/albums/missing")
        assert resp.status_code == 404


class TestPlexArtists:
    def test_get_artists(self, library_client):
        resp = library_client.get("/plex/artists")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Artist"


class TestPlexSearch:
    def test_search(self, library_client):
        resp = library_client.get("/plex/search?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert "albums" in data
        assert "artists" in data
        assert "tracks" in data

    def test_search_missing_query(self, library_client):
        resp = library_client.get("/plex/search")
        assert resp.status_code == 422


class TestPlexRecent:
    def test_get_recent(self, library_client):
        resp = library_client.get("/plex/recent")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestPlexGenres:
    def test_get_genres(self, library_client):
        resp = library_client.get("/plex/genres")
        assert resp.status_code == 200
        assert resp.json() == ["Rock", "Jazz"]

    def test_genres_502_on_external_error(self, library_client, mock_library_service):
        mock_library_service.get_genres = AsyncMock(side_effect=ExternalServiceError("down"))
        resp = library_client.get("/plex/genres")
        assert resp.status_code == 502


class TestPlexStats:
    def test_get_stats(self, library_client):
        resp = library_client.get("/plex/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tracks"] == 100
        assert data["total_albums"] == 10
        assert data["total_artists"] == 5


class TestPlexThumb:
    def test_get_thumb(self, library_client):
        resp = library_client.get("/plex/thumb/100")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_thumb_502_on_error(self, library_client, mock_repo):
        mock_repo.proxy_thumb = AsyncMock(side_effect=ExternalServiceError("timeout"))
        resp = library_client.get("/plex/thumb/100")
        assert resp.status_code == 502


class TestPlexAlbumMatch:
    def test_match_found(self, library_client):
        resp = library_client.get("/plex/album-match/mbid-1?name=Album&artist=Artist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["plex_album_id"] == "100"

    def test_match_not_found(self, library_client, mock_library_service):
        mock_library_service.get_album_match = AsyncMock(
            return_value=PlexAlbumMatch(found=False),
        )
        resp = library_client.get("/plex/album-match/mbid-1?name=Album&artist=Artist")
        assert resp.status_code == 200
        assert resp.json()["found"] is False

    def test_match_502_on_error(self, library_client, mock_library_service):
        mock_library_service.get_album_match = AsyncMock(
            side_effect=ExternalServiceError("down"),
        )
        resp = library_client.get("/plex/album-match/mbid-1")
        assert resp.status_code == 502


class TestPlexStreamRoutes:
    def test_scrobble(self, stream_client):
        resp = stream_client.post("/stream/plex/12345/scrobble")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_now_playing(self, stream_client):
        resp = stream_client.post("/stream/plex/12345/now-playing")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_scrobble_error(self, stream_client, mock_playback_service):
        mock_playback_service.scrobble = AsyncMock(return_value=False)
        resp = stream_client.post("/stream/plex/12345/scrobble")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_stream_head(self, stream_client, mock_playback_service):
        from fastapi.responses import Response
        mock_playback_service.proxy_head = AsyncMock(
            return_value=Response(status_code=200, headers={"Content-Length": "1000"}),
        )
        resp = stream_client.head("/stream/plex/library/parts/200/file.flac")
        assert resp.status_code == 200

    def test_stream_head_bad_request(self, stream_client, mock_playback_service):
        mock_playback_service.proxy_head = AsyncMock(side_effect=ValueError("bad"))
        resp = stream_client.head("/stream/plex/library/parts/200/file.flac")
        assert resp.status_code == 400

    def test_stream_502(self, stream_client, mock_playback_service):
        mock_playback_service.proxy_head = AsyncMock(side_effect=ExternalServiceError("down"))
        resp = stream_client.head("/stream/plex/library/parts/200/file.flac")
        assert resp.status_code == 502

    def test_get_stream_success(self, stream_client, mock_playback_service):
        from starlette.responses import StreamingResponse
        mock_playback_service.proxy_stream = AsyncMock(
            return_value=StreamingResponse(content=iter([b"audio"]), status_code=200),
        )
        resp = stream_client.get("/stream/plex/library/parts/200/file.flac")
        assert resp.status_code == 200

    def test_get_stream_bad_request(self, stream_client, mock_playback_service):
        mock_playback_service.proxy_stream = AsyncMock(side_effect=ValueError("bad"))
        resp = stream_client.get("/stream/plex/library/parts/200/file.flac")
        assert resp.status_code == 400

    def test_get_stream_502(self, stream_client, mock_playback_service):
        mock_playback_service.proxy_stream = AsyncMock(
            side_effect=ExternalServiceError("Plex streaming failed"),
        )
        resp = stream_client.get("/stream/plex/library/parts/200/file.flac")
        assert resp.status_code == 502

    def test_get_stream_416(self, stream_client, mock_playback_service):
        mock_playback_service.proxy_stream = AsyncMock(
            side_effect=ExternalServiceError("416 Range not satisfiable"),
        )
        resp = stream_client.get("/stream/plex/library/parts/200/file.flac")
        assert resp.status_code == 416


class TestPersonalPlaylistImage:
    def test_image_is_private_and_passes_requesting_user(
        self, library_client, mock_library_service
    ):
        resp = library_client.get("/plex/playlist-image/playlist-1/item-1?size=320")

        assert resp.status_code == 200
        assert resp.content == b"playlist-image"
        assert resp.headers["cache-control"] == "private, no-store"
        call = mock_library_service.get_playlist_image.await_args
        assert call.args[0:2] == ("playlist-1", "item-1")
        assert call.args[2].id == "test-user-id"
        assert call.args[3] == 320
