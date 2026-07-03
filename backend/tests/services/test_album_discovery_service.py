import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from api.v1.schemas.discovery import MoreByArtistResponse
from services.album_discovery_service import AlbumDiscoveryService


def _make_lb_repo(configured: bool = True) -> MagicMock:
    repo = MagicMock()
    repo.is_configured.return_value = configured
    repo.get_similar_artists = AsyncMock(return_value=[
        SimpleNamespace(artist_mbid="art-a", artist_name="Artist A"),
    ])
    repo.get_artist_top_release_groups = AsyncMock(return_value=[
        SimpleNamespace(
            release_group_mbid="rg-1",
            release_group_name="Album One",
            artist_name="Artist A",
            listen_count=10,
        ),
    ])
    return repo


def _make_factory(lb_repo=None) -> MagicMock:
    factory = MagicMock()
    factory.resolve_listenbrainz = AsyncMock(return_value=lb_repo)
    return factory


def _make_library_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_library_mbids = AsyncMock(return_value=set())
    repo.get_requested_mbids = AsyncMock(return_value=set())
    return repo


def _make_service(*, lb_repo=None, client_factory=None) -> AlbumDiscoveryService:
    return AlbumDiscoveryService(
        listenbrainz_repo=lb_repo if lb_repo is not None else _make_lb_repo(configured=False),
        musicbrainz_repo=AsyncMock(),
        library_db=AsyncMock(),
        library_repo=_make_library_repo(),
        client_factory=client_factory,
    )


class TestGetSimilarAlbumsPerUser:
    """With a client_factory, similar-albums follows the requesting user's link."""

    @pytest.mark.asyncio
    async def test_linked_user_returns_albums(self):
        lb_repo = _make_lb_repo()
        svc = _make_service(client_factory=_make_factory(lb_repo=lb_repo))

        result = await svc.get_similar_albums("album-x", "artist-x", user_id="user-1")

        assert result.configured is True
        assert [a.musicbrainz_id for a in result.albums] == ["rg-1"]
        svc._client_factory.resolve_listenbrainz.assert_awaited_once_with("user-1")

    @pytest.mark.asyncio
    async def test_unlinked_user_returns_not_configured(self):
        svc = _make_service(client_factory=_make_factory(lb_repo=None))

        result = await svc.get_similar_albums("album-x", "artist-x", user_id="user-1")

        assert result.configured is False
        assert result.albums == []

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_not_configured(self):
        svc = _make_service(client_factory=_make_factory(lb_repo=_make_lb_repo()))

        result = await svc.get_similar_albums("album-x", "artist-x")

        assert result.configured is False


class TestGetSimilarAlbumsFallback:
    """No client_factory (unit-test path) falls back to the injected global repo."""

    @pytest.mark.asyncio
    async def test_global_configured_returns_albums(self):
        svc = _make_service(lb_repo=_make_lb_repo(configured=True))

        result = await svc.get_similar_albums("album-x", "artist-x")

        assert result.configured is True
        assert [a.musicbrainz_id for a in result.albums] == ["rg-1"]

    @pytest.mark.asyncio
    async def test_global_unconfigured_returns_not_configured(self):
        svc = _make_service(lb_repo=_make_lb_repo(configured=False))

        result = await svc.get_similar_albums("album-x", "artist-x")

        assert result.configured is False

    @pytest.mark.asyncio
    async def test_factory_present_but_no_user_falls_back_to_global(self):
        """Background callers (e.g. album radio) with no user context still use a
        configured global repo rather than reporting not-configured."""
        global_repo = _make_lb_repo(configured=True)
        svc = _make_service(lb_repo=global_repo, client_factory=_make_factory(lb_repo=None))

        result = await svc.get_similar_albums("album-x", "artist-x")

        assert result.configured is True
        assert [a.musicbrainz_id for a in result.albums] == ["rg-1"]
        svc._client_factory.resolve_listenbrainz.assert_not_called()


class TestMoreByArtistUnaffected:
    """The 'More by Artist' rail is MusicBrainz-only and never gated on a music service."""

    @pytest.mark.asyncio
    async def test_returns_albums_without_any_connection(self):
        svc = _make_service(lb_repo=_make_lb_repo(configured=False))
        svc._mb_repo.get_release_groups_by_artist = AsyncMock(return_value=[
            {
                "id": "rg-2",
                "title": "Other Album",
                "artist-credit": [{"artist": {"name": "Artist X"}}],
                "first-release-date": "2020-05-01",
            },
        ])

        result = await svc.get_more_by_artist("artist-x", exclude_album_mbid="album-x")

        assert isinstance(result, MoreByArtistResponse)
        assert [a.musicbrainz_id for a in result.albums] == ["rg-2"]
        assert result.artist_name == "Artist X"


class TestSimilarAlbumsPopularityFallback:
    """Similar Albums must prefer ListenBrainz and only use Last.fm when LB popularity
    is DEFINITELY degraded."""

    def _clear(self):
        from infrastructure.service_health import service_health
        service_health.clear()

    @pytest.mark.asyncio
    async def test_uses_listenbrainz_when_healthy(self):
        self._clear()
        lb_repo = _make_lb_repo()
        lfm_repo = AsyncMock()
        svc = AlbumDiscoveryService(
            listenbrainz_repo=lb_repo, musicbrainz_repo=AsyncMock(),
            library_db=AsyncMock(), library_repo=_make_library_repo(),
            lastfm_repo=lfm_repo, mbid_svc=AsyncMock(),
        )
        resp = await svc.get_similar_albums("album-x", "art-x", count=5)
        assert [a.musicbrainz_id for a in resp.albums] == ["rg-1"]  # LB path
        lfm_repo.get_artist_top_albums.assert_not_called()
        self._clear()

    @pytest.mark.asyncio
    async def test_falls_back_to_lastfm_when_definitely_degraded(self):
        from infrastructure.service_health import service_health
        self._clear()
        # LB popularity returns nothing (degraded); similar-artists still work
        lb_repo = _make_lb_repo()
        lb_repo.get_artist_top_release_groups = AsyncMock(return_value=[])
        lfm_repo = AsyncMock()
        lfm_repo.get_artist_top_albums = AsyncMock(
            return_value=[SimpleNamespace(name="LFM Album", artist_name="Artist A", mbid="al-9")]
        )
        mbid_svc = AsyncMock()
        mbid_svc.lastfm_albums_to_queue_items = AsyncMock(
            return_value=[SimpleNamespace(
                release_group_mbid="rg-lfm", album_name="LFM Album",
                artist_name="Artist A", artist_mbid="art-a",
            )]
        )
        svc = AlbumDiscoveryService(
            listenbrainz_repo=lb_repo, musicbrainz_repo=AsyncMock(),
            library_db=AsyncMock(), library_repo=_make_library_repo(),
            lastfm_repo=lfm_repo, mbid_svc=mbid_svc,
        )

        service_health.mark_degraded("listenbrainz", "popularity", message="down")
        resp = await svc.get_similar_albums("album-x", "art-x", count=5)

        assert [a.musicbrainz_id for a in resp.albums] == ["rg-lfm"]
        lfm_repo.get_artist_top_albums.assert_awaited()
        self._clear()
