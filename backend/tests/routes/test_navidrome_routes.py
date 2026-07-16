from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.navidrome_library import (
    _get_user_music_folder_ids,
    router as library_router,
)
from api.v1.routes.stream import router as stream_router
from api.v1.schemas.navidrome import (
    NavidromeAlbumDetail,
    NavidromeAlbumMatch,
    NavidromeAlbumSummary,
    NavidromeArtistSummary,
    NavidromeLibraryStats,
    NavidromeSearchResponse,
    NavidromeTrackInfo,
)
from core.dependencies import (
    get_navidrome_folder_scope_service,
    get_navidrome_library_service,
    get_navidrome_playback_service,
)
from core.exceptions import ExternalServiceError
from infrastructure.resilience.retry import CircuitOpenError
from infrastructure.persistence.navidrome_folder_preferences_store import (
    NavidromeFolderPreference,
)
from services.navidrome_folder_scope_service import (
    NavidromeFolderResolution,
    NavidromeFolderScope,
)
from tests.helpers import override_user_auth


def _album_summary(id: str = "a1", name: str = "Album") -> NavidromeAlbumSummary:
    return NavidromeAlbumSummary(navidrome_id=id, name=name, artist_name="Artist")


def _track_info(id: str = "t1", title: str = "Track") -> NavidromeTrackInfo:
    return NavidromeTrackInfo(navidrome_id=id, title=title, track_number=1, duration_seconds=200.0)


def _artist_summary(id: str = "ar1", name: str = "Artist") -> NavidromeArtistSummary:
    return NavidromeArtistSummary(navidrome_id=id, name=name)


@pytest.fixture
def mock_library_service():
    mock = MagicMock()
    mock.get_albums = AsyncMock(return_value=[_album_summary()])
    mock.get_album_detail = AsyncMock(return_value=NavidromeAlbumDetail(
        navidrome_id="a1", name="Album", tracks=[_track_info()],
    ))
    mock.get_artists = AsyncMock(return_value=[_artist_summary()])
    mock.get_artist_detail = AsyncMock(return_value={
        "artist": {"navidrome_id": "ar1", "name": "Artist", "image_url": None, "album_count": 0, "musicbrainz_id": None},
        "albums": [{"navidrome_id": "a1", "name": "Album", "artist_name": "Artist", "year": None, "track_count": 0, "image_url": None, "musicbrainz_id": None}],
    })
    mock.search = AsyncMock(return_value=NavidromeSearchResponse(
        albums=[_album_summary()], artists=[_artist_summary()], tracks=[_track_info()],
    ))
    mock.get_recent = AsyncMock(return_value=[_album_summary()])
    mock.get_favorites = AsyncMock(return_value=NavidromeSearchResponse())
    mock.get_genres = AsyncMock(return_value=["Rock", "Jazz"])
    mock.get_stats = AsyncMock(return_value=NavidromeLibraryStats(
        total_tracks=100, total_albums=10, total_artists=5,
    ))
    mock.get_album_match = AsyncMock(return_value=NavidromeAlbumMatch(found=True, navidrome_album_id="nd-1"))
    return mock


@pytest.fixture
def mock_playback_service():
    mock = MagicMock()
    mock.get_stream_url = MagicMock(return_value="http://navidrome:4533/rest/stream?id=s1&u=admin")
    mock.scrobble = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def library_client(mock_library_service):
    app = FastAPI()
    app.include_router(library_router)
    app.dependency_overrides[get_navidrome_library_service] = lambda: mock_library_service
    app.dependency_overrides[_get_user_music_folder_ids] = lambda: None
    override_user_auth(app)
    return TestClient(app)


@pytest.fixture
def stream_client(mock_playback_service):
    app = FastAPI()
    app.include_router(stream_router)
    app.dependency_overrides[get_navidrome_playback_service] = lambda: mock_playback_service
    override_user_auth(app)
    return TestClient(app)


class TestLibraryAlbums:
    def test_get_albums(self, library_client):
        resp = library_client.get("/navidrome/albums")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["navidrome_id"] == "a1"
        assert data["total"] == 1

    def test_get_albums_stats_fallback(self, library_client, mock_library_service):
        """When stats fails, albums still returns with heuristic total."""
        mock_library_service.get_albums = AsyncMock(return_value=[_album_summary(id=f"a{i}") for i in range(48)])
        mock_library_service.get_stats = AsyncMock(side_effect=ExternalServiceError("Library not found"))
        resp = library_client.get("/navidrome/albums?limit=48")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 48
        assert data["total"] == 49  # offset(0) + 48 + 1 (full page heuristic)

    def test_get_albums_stats_fallback_partial_page(self, library_client, mock_library_service):
        """Partial page + stats failure → total = offset + len(items), no +1."""
        mock_library_service.get_albums = AsyncMock(return_value=[_album_summary(id=f"a{i}") for i in range(5)])
        mock_library_service.get_stats = AsyncMock(side_effect=ExternalServiceError("down"))
        resp = library_client.get("/navidrome/albums?limit=48")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5

    def test_get_albums_stats_fallback_circuit_open(self, library_client, mock_library_service):
        """When CB is open, stats raises CircuitOpenError - albums still work."""
        mock_library_service.get_albums = AsyncMock(return_value=[_album_summary(id=f"a{i}") for i in range(48)])
        mock_library_service.get_stats = AsyncMock(
            side_effect=CircuitOpenError("Circuit breaker 'navidrome' is OPEN", breaker_name="navidrome"),
        )
        resp = library_client.get("/navidrome/albums?limit=48")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 48
        assert data["total"] == 49

    def test_get_album_detail(self, library_client):
        resp = library_client.get("/navidrome/albums/a1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Album"
        assert len(data["tracks"]) == 1

    def test_get_album_detail_not_found(self, library_client, mock_library_service):
        mock_library_service.get_album_detail = AsyncMock(return_value=None)
        resp = library_client.get("/navidrome/albums/missing")
        assert resp.status_code == 404

    def test_get_albums_502_on_external_error(self, library_client, mock_library_service):
        mock_library_service.get_albums = AsyncMock(side_effect=ExternalServiceError("down"))
        resp = library_client.get("/navidrome/albums")
        assert resp.status_code == 502


class TestLibraryArtists:
    def test_get_artists(self, library_client):
        resp = library_client.get("/navidrome/artists")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Artist"

    def test_get_artist_detail(self, library_client):
        resp = library_client.get("/navidrome/artists/ar1")
        assert resp.status_code == 200
        data = resp.json()
        assert "artist" in data
        assert "albums" in data

    def test_get_artist_detail_not_found(self, library_client, mock_library_service):
        mock_library_service.get_artist_detail = AsyncMock(return_value=None)
        resp = library_client.get("/navidrome/artists/missing")
        assert resp.status_code == 404


class TestLibrarySearch:
    def test_search(self, library_client):
        resp = library_client.get("/navidrome/search?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert "albums" in data
        assert "artists" in data
        assert "tracks" in data

    def test_search_missing_query(self, library_client):
        resp = library_client.get("/navidrome/search")
        assert resp.status_code == 422

    def test_two_users_receive_only_their_selected_folder_scope(self):
        scope_service = AsyncMock()

        async def resolve(user_id):
            folder_id = "folder-a" if user_id == "alice" else "folder-b"
            preference = NavidromeFolderPreference(
                "selected", (folder_id,), "server-1", 1.0
            )
            return NavidromeFolderResolution(
                preference=preference,
                scope=NavidromeFolderScope("selected", (folder_id,)),
            )

        scope_service.resolve.side_effect = resolve
        service = MagicMock()

        async def search(_query, folder_ids):
            track_id = "track-a" if folder_ids == ("folder-a",) else "track-b"
            return NavidromeSearchResponse(tracks=[_track_info(track_id)])

        service.search = AsyncMock(side_effect=search)

        def client_for(user_id):
            app = FastAPI()
            app.include_router(library_router)
            app.dependency_overrides[get_navidrome_library_service] = lambda: service
            app.dependency_overrides[get_navidrome_folder_scope_service] = (
                lambda: scope_service
            )
            override_user_auth(app, user_id=user_id)
            return TestClient(app)

        alice = client_for("alice").get("/navidrome/search?q=song").json()
        bob = client_for("bob").get("/navidrome/search?q=song").json()

        assert [track["navidrome_id"] for track in alice["tracks"]] == ["track-a"]
        assert [track["navidrome_id"] for track in bob["tracks"]] == ["track-b"]
        assert service.search.await_args_list[0].args[1] == ("folder-a",)
        assert service.search.await_args_list[1].args[1] == ("folder-b",)


class TestLibraryRecent:
    def test_get_recent(self, library_client):
        resp = library_client.get("/navidrome/recent")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestLibraryFavorites:
    def test_get_favorites(self, library_client):
        resp = library_client.get("/navidrome/favorites")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestLibraryGenres:
    def test_get_genres(self, library_client):
        resp = library_client.get("/navidrome/genres")
        assert resp.status_code == 200
        assert resp.json() == ["Rock", "Jazz"]

    def test_genres_502_on_external_error(self, library_client, mock_library_service):
        mock_library_service.get_genres = AsyncMock(side_effect=ExternalServiceError("down"))
        resp = library_client.get("/navidrome/genres")
        assert resp.status_code == 502


class TestLibraryStats:
    def test_get_stats(self, library_client):
        resp = library_client.get("/navidrome/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tracks"] == 100
        assert data["total_albums"] == 10
        assert data["total_artists"] == 5


class TestAlbumMatch:
    def test_album_match(self, library_client):
        resp = library_client.get("/navidrome/album-match/mb-1?name=Album&artist=Artist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["navidrome_album_id"] == "nd-1"


class TestNavidromeStreamProxy:
    def test_stream_returns_streaming_response(self, stream_client, mock_playback_service):
        from fastapi.responses import StreamingResponse

        async def fake_chunks():
            yield b"audio-data"

        mock_response = StreamingResponse(
            content=fake_chunks(),
            status_code=200,
            headers={"Content-Type": "audio/mpeg"},
            media_type="audio/mpeg",
        )
        mock_playback_service.proxy_stream = AsyncMock(return_value=mock_response)

        resp = stream_client.get("/stream/navidrome/s1")
        assert resp.status_code == 200

    def test_stream_returns_400_when_not_configured(self, stream_client, mock_playback_service):
        mock_playback_service.proxy_stream = AsyncMock(side_effect=ValueError("not configured"))
        resp = stream_client.get("/stream/navidrome/s1")
        assert resp.status_code == 400


class TestNavidromeScrobble:
    def test_scrobble_returns_ok(self, stream_client):
        resp = stream_client.post("/stream/navidrome/s1/scrobble")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_scrobble_failure_returns_error(self, stream_client, mock_playback_service):
        mock_playback_service.scrobble = AsyncMock(return_value=False)
        resp = stream_client.post("/stream/navidrome/s1/scrobble")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
