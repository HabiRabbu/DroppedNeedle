import pytest
from unittest.mock import AsyncMock, MagicMock

from repositories.lastfm_models import LastFmAlbum
from services.artist_discovery_service import ArtistDiscoveryService


ARTIST_MBID = "f4a31f0a-51dd-4fa7-986d-3095c40c5ed9"
RELEASE_MBID_1 = "aaaaaaaa-0000-0000-0000-000000000001"
RELEASE_MBID_2 = "aaaaaaaa-0000-0000-0000-000000000002"


def _make_lastfm_albums() -> list[LastFmAlbum]:
    return [
        LastFmAlbum(name="Album A", artist_name="Test Artist", mbid=RELEASE_MBID_1, playcount=5000),
        LastFmAlbum(name="Album B", artist_name="Test Artist", mbid=RELEASE_MBID_2, playcount=3000),
        LastFmAlbum(name="Album C (no mbid)", artist_name="Test Artist", mbid="", playcount=1000),
    ]


def _make_service() -> tuple[ArtistDiscoveryService, AsyncMock]:
    lb_repo = MagicMock()
    lb_repo.is_configured.return_value = False

    lastfm_repo = AsyncMock()
    lastfm_repo.get_artist_top_albums = AsyncMock(return_value=_make_lastfm_albums())

    prefs = MagicMock()
    prefs.is_lastfm_enabled.return_value = True

    library_db = AsyncMock()
    library_db.get_all_artist_mbids = AsyncMock(return_value=set())

    memory_cache = AsyncMock()
    memory_cache.get = AsyncMock(return_value=None)
    memory_cache.set = AsyncMock()

    mb_repo = AsyncMock()
    mb_repo.get_release_group_id_from_release = AsyncMock(
        side_effect=AssertionError("MusicBrainz resolution should NOT be called for Last.fm top-albums")
    )

    library_repo = AsyncMock()
    library_repo.get_library_mbids = AsyncMock(return_value={RELEASE_MBID_1})
    library_repo.get_requested_mbids = AsyncMock(return_value={RELEASE_MBID_2})

    svc = ArtistDiscoveryService(
        listenbrainz_repo=lb_repo,
        musicbrainz_repo=mb_repo,
        library_db=library_db,
        library_repo=library_repo,
        memory_cache=memory_cache,
        lastfm_repo=lastfm_repo,
        preferences_service=prefs,
    )
    return svc, mb_repo


class TestLastFmTopAlbumsNoResolution:
    @pytest.mark.asyncio
    async def test_no_musicbrainz_resolution_called(self):
        svc, mb_repo = _make_service()

        result = await svc.get_top_albums(ARTIST_MBID, count=10, source="lastfm")

        assert len(result.albums) == 3
        mb_repo.get_release_group_id_from_release.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_raw_lastfm_mbid(self):
        svc, _ = _make_service()

        result = await svc.get_top_albums(ARTIST_MBID, count=10, source="lastfm")

        assert result.albums[0].release_group_mbid == RELEASE_MBID_1
        assert result.albums[1].release_group_mbid == RELEASE_MBID_2
        assert result.albums[2].release_group_mbid is None

    @pytest.mark.asyncio
    async def test_library_flags_use_raw_mbid(self):
        svc, _ = _make_service()

        result = await svc.get_top_albums(ARTIST_MBID, count=10, source="lastfm")

        assert result.albums[0].in_library is True
        assert result.albums[0].requested is False
        assert result.albums[1].in_library is False
        assert result.albums[1].requested is True
        assert result.albums[2].in_library is False
        assert result.albums[2].requested is False

    @pytest.mark.asyncio
    async def test_source_is_lastfm(self):
        svc, _ = _make_service()

        result = await svc.get_top_albums(ARTIST_MBID, count=10, source="lastfm")

        assert result.source == "lastfm"
