"""Artist/album discovery endpoints resolve discovery per requesting user: the
route must forward current_user.id into the discovery service and reject
unauthenticated callers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, FastAPI

from api.v1.routes import albums as albums_routes
from api.v1.routes import artists as artists_routes
from api.v1.schemas.discovery import (
    SimilarAlbumsResponse,
    SimilarArtistsResponse,
    TopAlbumsResponse,
    TopSongsResponse,
)
from core.dependencies import get_album_discovery_service, get_artist_discovery_service
from middleware import _get_current_user
from tests.helpers import build_test_client, mock_user

MBID = "f4a31f0a-51dd-4fa7-986d-3095c40c5ed9"
ARTIST_MBID = "a1b2c3d4-0000-0000-0000-000000000001"


def _artist_service() -> MagicMock:
    svc = MagicMock()
    svc.get_similar_artists = AsyncMock(return_value=SimilarArtistsResponse(similar_artists=[]))
    svc.get_top_songs = AsyncMock(return_value=TopSongsResponse(songs=[]))
    svc.get_top_albums = AsyncMock(return_value=TopAlbumsResponse(albums=[]))
    return svc


def _album_service() -> MagicMock:
    svc = MagicMock()
    svc.get_similar_albums = AsyncMock(return_value=SimilarAlbumsResponse(albums=[]))
    return svc


def _build(*, authed: bool):
    app = FastAPI()
    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(artists_routes.router)
    v1.include_router(albums_routes.router)
    app.include_router(v1)

    artist_svc = _artist_service()
    album_svc = _album_service()
    app.dependency_overrides[get_artist_discovery_service] = lambda: artist_svc
    app.dependency_overrides[get_album_discovery_service] = lambda: album_svc
    if authed:
        app.dependency_overrides[_get_current_user] = lambda: mock_user(user_id="user-9")
    return build_test_client(app), artist_svc, album_svc


class TestForwardsUserId:
    def test_similar_artists_forwards_user_id(self):
        client, artist_svc, _ = _build(authed=True)
        resp = client.get(f"/api/v1/artists/{MBID}/similar")
        assert resp.status_code == 200
        assert artist_svc.get_similar_artists.await_args.kwargs["user_id"] == "user-9"

    def test_top_songs_forwards_user_id(self):
        client, artist_svc, _ = _build(authed=True)
        resp = client.get(f"/api/v1/artists/{MBID}/top-songs")
        assert resp.status_code == 200
        assert artist_svc.get_top_songs.await_args.kwargs["user_id"] == "user-9"

    def test_top_albums_forwards_user_id(self):
        client, artist_svc, _ = _build(authed=True)
        resp = client.get(f"/api/v1/artists/{MBID}/top-albums")
        assert resp.status_code == 200
        assert artist_svc.get_top_albums.await_args.kwargs["user_id"] == "user-9"

    def test_similar_albums_forwards_user_id(self):
        client, _, album_svc = _build(authed=True)
        resp = client.get(f"/api/v1/albums/{MBID}/similar?artist_id={ARTIST_MBID}")
        assert resp.status_code == 200
        assert album_svc.get_similar_albums.await_args.kwargs["user_id"] == "user-9"


class TestRejectsUnauthenticated:
    @pytest.mark.parametrize("path", [
        f"/api/v1/artists/{MBID}/similar",
        f"/api/v1/artists/{MBID}/top-songs",
        f"/api/v1/artists/{MBID}/top-albums",
        f"/api/v1/albums/{MBID}/similar?artist_id={ARTIST_MBID}",
    ])
    def test_unauthenticated_rejected(self, path):
        client, _, _ = _build(authed=False)
        assert client.get(path).status_code == 401
