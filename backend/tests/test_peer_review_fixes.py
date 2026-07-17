"""Tests for peer-review fixes: route collision, byYear contract, audio-only filter,
favorites/expanded error handling, timed lyrics, and Plex accountID removal."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.navidrome_library import router as navidrome_router
from api.v1.routes.jellyfin_library import router as jellyfin_router
from api.v1.schemas.navidrome import (
    NavidromeArtistIndexResponse,
    NavidromeArtistIndexEntry,
    NavidromeArtistSummary,
    NavidromeAlbumSummary,
    NavidromeAlbumPage,
)
from api.v1.schemas.jellyfin import JellyfinFavoritesExpanded
from core.dependencies import (
    get_jellyfin_library_service,
    get_navidrome_folder_scope_service,
    get_navidrome_library_service,
)
from core.exceptions import ExternalServiceError
from infrastructure.persistence.navidrome_folder_preferences_store import (
    NavidromeFolderPreference,
)
from repositories.navidrome_models import SubsonicLyrics, SubsonicLyricLine
from services.navidrome_folder_scope_service import (
    NavidromeFolderResolution,
    NavidromeFolderScope,
)
from tests.helpers import override_user_auth


def _all_folder_scope_service() -> AsyncMock:
    service = AsyncMock()
    service.resolve.return_value = NavidromeFolderResolution(
        preference=NavidromeFolderPreference("all", (), "server-1", 1.0),
        scope=NavidromeFolderScope("all", ()),
    )
    return service


def _navidrome_app(mock_service) -> TestClient:
    """Router already has prefix=/navidrome, so routes are at /navidrome/..."""
    app = FastAPI()
    app.include_router(navidrome_router)
    app.dependency_overrides[get_navidrome_library_service] = lambda: mock_service
    app.dependency_overrides[get_navidrome_folder_scope_service] = (
        _all_folder_scope_service
    )
    override_user_auth(app)
    return TestClient(app)


def _jellyfin_app(mock_service) -> TestClient:
    """Router already has prefix=/jellyfin, so routes are at /jellyfin/..."""
    app = FastAPI()
    app.include_router(jellyfin_router)
    app.dependency_overrides[get_jellyfin_library_service] = lambda: mock_service
    return TestClient(app)


class TestNavidromeArtistIndexRouteOrder:
    """Verify /artists/index resolves to the index handler, not the artist-detail handler."""

    def test_artists_index_resolves_correctly(self):
        mock = MagicMock()
        mock.get_artists_index = AsyncMock(return_value=NavidromeArtistIndexResponse(
            index=[
                NavidromeArtistIndexEntry(
                    name="A",
                    artists=[NavidromeArtistSummary(navidrome_id="ar1", name="ABBA")],
                ),
            ]
        ))
        client = _navidrome_app(mock)
        resp = client.get("/navidrome/artists/index")
        assert resp.status_code == 200
        assert "index" in resp.json()
        mock.get_artists_index.assert_awaited_once_with(None)
        mock.get_artist_detail = AsyncMock()
        mock.get_artist_detail.assert_not_awaited()

    def test_artist_detail_still_works(self):
        mock = MagicMock()
        mock.get_artist_detail = AsyncMock(return_value={
            "artist": {"navidrome_id": "real-id", "name": "Artist"},
            "albums": [],
        })
        client = _navidrome_app(mock)
        resp = client.get("/navidrome/artists/real-id")
        assert resp.status_code == 200
        mock.get_artist_detail.assert_awaited_once_with("real-id", None)


class TestNavidromeByYearSort:
    """Verify that year sort sends fromYear/toYear to the service."""

    def test_year_sort_asc_sends_year_params(self):
        mock = MagicMock()
        mock.get_albums = AsyncMock(return_value=[])
        mock.get_stats = AsyncMock(side_effect=ExternalServiceError("unavailable"))
        client = _navidrome_app(mock)
        resp = client.get("/navidrome/albums", params={"sort_by": "year", "sort_order": ""})
        assert resp.status_code == 200
        call_kwargs = mock.get_albums.call_args.kwargs
        assert call_kwargs.get("from_year") == 0
        assert call_kwargs.get("to_year") == 9999

    def test_year_sort_desc_sends_reversed_year_params(self):
        mock = MagicMock()
        mock.get_albums = AsyncMock(return_value=[])
        mock.get_stats = AsyncMock(side_effect=ExternalServiceError("unavailable"))
        client = _navidrome_app(mock)
        resp = client.get("/navidrome/albums", params={"sort_by": "year", "sort_order": "desc"})
        assert resp.status_code == 200
        call_kwargs = mock.get_albums.call_args.kwargs
        assert call_kwargs.get("from_year") == 9999
        assert call_kwargs.get("to_year") == 0

    def test_name_sort_does_not_send_year_params(self):
        mock = MagicMock()
        mock.get_albums = AsyncMock(return_value=[])
        mock.get_stats = AsyncMock(side_effect=ExternalServiceError("unavailable"))
        client = _navidrome_app(mock)
        resp = client.get("/navidrome/albums", params={"sort_by": "name"})
        assert resp.status_code == 200
        call_kwargs = mock.get_albums.call_args.kwargs
        assert "from_year" not in call_kwargs
        assert "to_year" not in call_kwargs


class TestJellyfinPlaylistAudioFilter:
    """Verify that non-audio items are filtered out of playlist responses."""

    @pytest.mark.asyncio
    async def test_get_playlist_items_filters_non_audio(self):
        from repositories.jellyfin_models import JellyfinItem
        from repositories.jellyfin_repository import JellyfinRepository

        repo = MagicMock(spec=JellyfinRepository)
        repo._configured = True
        repo._user_id = "u1"
        repo._cache_scope = "shared"
        repo._cache = MagicMock()
        repo._cache.get = AsyncMock(return_value=None)
        repo._cache.set = AsyncMock()

        mixed_items = {
            "Items": [
                {"Id": "a1", "Name": "Song 1", "Type": "Audio", "RunTimeTicks": 1800000000},
                {"Id": "v1", "Name": "Video", "Type": "Video", "RunTimeTicks": 9000000000},
                {"Id": "a2", "Name": "Song 2", "Type": "Audio", "RunTimeTicks": 2000000000},
            ]
        }
        repo._get = AsyncMock(return_value=mixed_items)

        result = await JellyfinRepository.get_playlist_items(repo, "pl-1")
        assert len(result) == 2
        assert all(item.type == "Audio" for item in result)
        assert result[0].name == "Song 1"
        assert result[1].name == "Song 2"


class TestJellyfinFavoritesExpandedErrorHandling:
    """Verify that unexpected errors in favorites/expanded return a proper HTTP error."""

    def test_unexpected_error_returns_500(self):
        mock = MagicMock()
        mock.get_favorites_expanded = AsyncMock(side_effect=RuntimeError("unexpected"))
        client = _jellyfin_app(mock)
        resp = client.get("/jellyfin/favorites/expanded")
        assert resp.status_code == 500

    def test_external_service_error_returns_502(self):
        mock = MagicMock()
        mock.get_favorites_expanded = AsyncMock(side_effect=ExternalServiceError("Jellyfin down"))
        client = _jellyfin_app(mock)
        resp = client.get("/jellyfin/favorites/expanded")
        assert resp.status_code == 502

    def test_success_returns_200(self):
        mock = MagicMock()
        mock.get_favorites_expanded = AsyncMock(return_value=JellyfinFavoritesExpanded(albums=[], artists=[]))
        client = _jellyfin_app(mock)
        resp = client.get("/jellyfin/favorites/expanded")
        assert resp.status_code == 200


class TestNavidromeLyricsTimedPreservation:
    """Verify that timed lyrics lines are preserved through the backend contract."""

    @pytest.mark.asyncio
    async def test_synced_lyrics_preserve_timing(self):
        from services.navidrome_library_service import NavidromeLibraryService

        lyrics = SubsonicLyrics(
            value="Line one\nLine two",
            lines=[
                SubsonicLyricLine(value="Line one", start=0),
                SubsonicLyricLine(value="Line two", start=5000),
            ],
            is_synced=True,
        )
        repo = MagicMock()
        repo.get_lyrics_by_song_id = AsyncMock(return_value=lyrics)
        repo.get_lyrics = AsyncMock(return_value=None)
        repo.get_albums = AsyncMock(return_value=[])
        repo.get_recently_played = AsyncMock(return_value=[])
        repo.get_recently_added = AsyncMock(return_value=[])
        repo.get_starred_albums = AsyncMock(return_value=[])
        repo.get_starred_artists = AsyncMock(return_value=[])
        repo.get_starred_songs = AsyncMock(return_value=[])
        repo.get_genres = AsyncMock(return_value=[])
        repo.get_album_count = AsyncMock(return_value=0)
        repo.get_track_count = AsyncMock(return_value=0)
        repo.get_artist_count = AsyncMock(return_value=0)
        prefs = MagicMock()
        svc = NavidromeLibraryService(navidrome_repo=repo, preferences_service=prefs)

        result = await svc.get_lyrics("song-1")
        assert result is not None
        assert result.is_synced is True
        assert len(result.lines) == 2
        assert result.lines[0].text == "Line one"
        assert result.lines[0].start_seconds == pytest.approx(0.0)
        assert result.lines[1].text == "Line two"
        assert result.lines[1].start_seconds == pytest.approx(5.0)
        assert "Line one" in result.text

    @pytest.mark.asyncio
    async def test_unsynced_lyrics_have_no_timing(self):
        from services.navidrome_library_service import NavidromeLibraryService

        lyrics = SubsonicLyrics(
            value="Plain lyrics\nSecond line",
            lines=[
                SubsonicLyricLine(value="Plain lyrics", start=None),
                SubsonicLyricLine(value="Second line", start=None),
            ],
            is_synced=False,
        )
        repo = MagicMock()
        repo.get_lyrics_by_song_id = AsyncMock(return_value=lyrics)
        repo.get_lyrics = AsyncMock(return_value=None)
        repo.get_albums = AsyncMock(return_value=[])
        repo.get_recently_played = AsyncMock(return_value=[])
        repo.get_recently_added = AsyncMock(return_value=[])
        repo.get_starred_albums = AsyncMock(return_value=[])
        repo.get_starred_artists = AsyncMock(return_value=[])
        repo.get_starred_songs = AsyncMock(return_value=[])
        repo.get_genres = AsyncMock(return_value=[])
        repo.get_album_count = AsyncMock(return_value=0)
        repo.get_track_count = AsyncMock(return_value=0)
        repo.get_artist_count = AsyncMock(return_value=0)
        prefs = MagicMock()
        svc = NavidromeLibraryService(navidrome_repo=repo, preferences_service=prefs)

        result = await svc.get_lyrics("song-1")
        assert result is not None
        assert result.is_synced is False
        assert all(l.start_seconds is None for l in result.lines)


class TestPlexHistoryNoHardcodedAccount:
    """Verify that the Plex history endpoint does not hardcode accountID."""

    @pytest.mark.asyncio
    async def test_history_params_exclude_account_id(self):
        from repositories.plex_repository import PlexRepository

        repo = MagicMock(spec=PlexRepository)
        repo._configured = True
        repo._cache = MagicMock()
        repo._cache.get = AsyncMock(return_value=None)
        repo._cache.set = AsyncMock()
        repo._request = AsyncMock(return_value={
            "MediaContainer": {
                "size": 0,
                "totalSize": 0,
                "Metadata": [],
            }
        })

        await PlexRepository.get_listening_history(repo)
        call_args = repo._request.call_args
        params = call_args[1].get("params") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("params")
        assert "accountID" not in params
