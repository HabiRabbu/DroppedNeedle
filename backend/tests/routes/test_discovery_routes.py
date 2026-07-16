"""Route tests for discovery endpoints across Navidrome, Jellyfin, and Plex."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ROOT_APP_DIR", tempfile.mkdtemp())

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.navidrome_library import router as navidrome_router
from api.v1.routes.jellyfin_library import router as jellyfin_router
from api.v1.routes.plex_library import router as plex_router
from api.v1.schemas.navidrome import NavidromeTrackInfo
from api.v1.schemas.jellyfin import JellyfinTrackInfo
from api.v1.schemas.plex import PlexDiscoveryAlbum, PlexDiscoveryHub, PlexDiscoveryResponse
from core.dependencies import (
    get_navidrome_folder_scope_service,
    get_navidrome_library_service,
    get_jellyfin_library_service,
    get_plex_library_service,
    get_plex_repository,
)
from infrastructure.persistence.navidrome_folder_preferences_store import (
    NavidromeFolderPreference,
)
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


def _nd_track(id: str = "t1", title: str = "Track") -> NavidromeTrackInfo:
    return NavidromeTrackInfo(navidrome_id=id, title=title, track_number=1, duration_seconds=200.0)


def _jf_track(id: str = "jt1", title: str = "JTrack") -> JellyfinTrackInfo:
    return JellyfinTrackInfo(
        jellyfin_id=id, title=title, track_number=1, duration_seconds=180.0,
        album_name="Album", artist_name="Artist",
    )


class TestNavidromeRandomRoute:
    @pytest.fixture
    def _setup(self):
        self.mock_svc = MagicMock()
        self.mock_svc.get_random_songs = AsyncMock(return_value=[_nd_track()])
        app = FastAPI()
        app.include_router(navidrome_router)
        app.dependency_overrides[get_navidrome_library_service] = lambda: self.mock_svc
        app.dependency_overrides[get_navidrome_folder_scope_service] = (
            _all_folder_scope_service
        )
        override_user_auth(app)
        self.client = TestClient(app)

    def test_random_default(self, _setup):
        resp = self.client.get("/navidrome/random")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["navidrome_id"] == "t1"

    def test_random_with_params(self, _setup):
        self.mock_svc.get_random_songs = AsyncMock(return_value=[_nd_track(), _nd_track(id="t2")])
        resp = self.client.get("/navidrome/random?size=5&genre=Rock")
        assert resp.status_code == 200
        self.mock_svc.get_random_songs.assert_awaited_once_with(
            size=5, genre="Rock", music_folder_ids=None
        )

    def test_random_empty(self, _setup):
        self.mock_svc.get_random_songs = AsyncMock(return_value=[])
        resp = self.client.get("/navidrome/random")
        assert resp.status_code == 200
        assert resp.json() == []


class TestJellyfinInstantMixRoutes:
    @pytest.fixture
    def _setup(self):
        self.mock_svc = MagicMock()
        self.mock_svc.get_instant_mix = AsyncMock(return_value=[_jf_track()])
        self.mock_svc.get_instant_mix_by_artist = AsyncMock(return_value=[_jf_track()])
        self.mock_svc.get_instant_mix_by_genre = AsyncMock(return_value=[_jf_track()])
        app = FastAPI()
        app.include_router(jellyfin_router)
        app.dependency_overrides[get_jellyfin_library_service] = lambda: self.mock_svc
        self.client = TestClient(app)

    def test_instant_mix_by_item(self, _setup):
        resp = self.client.get("/jellyfin/instant-mix/album-123")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        self.mock_svc.get_instant_mix.assert_awaited_once_with("album-123", limit=50)

    def test_instant_mix_by_item_custom_limit(self, _setup):
        resp = self.client.get("/jellyfin/instant-mix/item-1?limit=10")
        assert resp.status_code == 200
        self.mock_svc.get_instant_mix.assert_awaited_once_with("item-1", limit=10)

    def test_instant_mix_by_artist(self, _setup):
        resp = self.client.get("/jellyfin/instant-mix/artist/art-456")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        self.mock_svc.get_instant_mix_by_artist.assert_awaited_once_with("art-456", limit=50)

    def test_instant_mix_by_genre(self, _setup):
        resp = self.client.get("/jellyfin/instant-mix/genre?genre=Rock")
        assert resp.status_code == 200
        self.mock_svc.get_instant_mix_by_genre.assert_awaited_once_with("Rock", limit=50)

    def test_instant_mix_by_genre_missing_param(self, _setup):
        resp = self.client.get("/jellyfin/instant-mix/genre")
        assert resp.status_code == 422

    def test_instant_mix_empty(self, _setup):
        self.mock_svc.get_instant_mix = AsyncMock(return_value=[])
        resp = self.client.get("/jellyfin/instant-mix/no-tracks")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPlexDiscoveryRoute:
    @pytest.fixture
    def _setup(self):
        self.mock_svc = MagicMock()
        self.mock_svc.get_discovery_hubs = AsyncMock(return_value=PlexDiscoveryResponse(
            hubs=[PlexDiscoveryHub(
                title="Recommended",
                hub_type="album",
                albums=[PlexDiscoveryAlbum(
                    plex_id="p1", name="Album", artist_name="Artist",
                    year=2024, image_url="/cover",
                )],
            )]
        ))
        self.mock_repo = MagicMock()
        app = FastAPI()
        app.include_router(plex_router)
        app.dependency_overrides[get_plex_library_service] = lambda: self.mock_svc
        app.dependency_overrides[get_plex_repository] = lambda: self.mock_repo
        self.client = TestClient(app)

    def test_discovery_returns_hubs(self, _setup):
        resp = self.client.get("/plex/discovery")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["hubs"]) == 1
        assert data["hubs"][0]["title"] == "Recommended"
        assert data["hubs"][0]["albums"][0]["plex_id"] == "p1"

    def test_discovery_empty(self, _setup):
        self.mock_svc.get_discovery_hubs = AsyncMock(return_value=PlexDiscoveryResponse(hubs=[]))
        resp = self.client.get("/plex/discovery")
        assert resp.status_code == 200
        assert resp.json()["hubs"] == []

    def test_discovery_custom_count(self, _setup):
        resp = self.client.get("/plex/discovery?count=5")
        assert resp.status_code == 200
        self.mock_svc.get_discovery_hubs.assert_awaited_once_with(count=5)
