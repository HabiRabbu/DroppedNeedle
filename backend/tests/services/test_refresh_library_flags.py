"""Lidarr monitored translation removed (follow state lives in FollowStore);
_refresh_library_flags only reconciles in_library and per-release flags."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from models.artist import ArtistInfo
from services.artist_service import ArtistService


@pytest.fixture
def mock_library_repo():
    repo = AsyncMock()
    repo.is_configured = MagicMock(return_value=True)
    repo.get_library_mbids.return_value = set()
    repo.get_requested_mbids.return_value = set()
    repo.get_artist_mbids.return_value = set()
    repo.get_artist_details.return_value = None
    return repo


@pytest.fixture
def artist_service(mock_library_repo):
    return ArtistService(
        mb_repo=AsyncMock(),
        library_repo=mock_library_repo,
        wikidata_repo=AsyncMock(),
        preferences_service=MagicMock(),
        memory_cache=AsyncMock(),
        disk_cache=AsyncMock(),
    )


def _make_artist(
    mbid: str = "aaa-bbb", in_library: bool = False, auto_download: bool = False
) -> ArtistInfo:
    return ArtistInfo(
        name="Test Artist",
        musicbrainz_id=mbid,
        in_library=in_library,
        auto_download=auto_download,
    )


class TestRefreshLibraryFlagsLibraryTransition:
    @pytest.mark.asyncio
    async def test_transition_sets_in_library(self, artist_service, mock_library_repo):
        mock_library_repo.get_artist_mbids.return_value = {"aaa-bbb"}
        artist = _make_artist(in_library=False)

        await artist_service._refresh_library_flags(artist)

        assert artist.in_library is True
        assert artist.auto_download is False

    @pytest.mark.asyncio
    async def test_already_in_library_preserves_auto_download(
        self, artist_service, mock_library_repo
    ):
        mock_library_repo.get_artist_mbids.return_value = {"aaa-bbb"}
        artist = _make_artist(in_library=True, auto_download=True)

        await artist_service._refresh_library_flags(artist)

        assert artist.in_library is True
        assert artist.auto_download is True

    @pytest.mark.asyncio
    async def test_removed_from_artist_mbids_clears_in_library(
        self, artist_service, mock_library_repo
    ):
        mock_library_repo.get_artist_mbids.return_value = set()
        artist = _make_artist(in_library=True, auto_download=True)

        await artist_service._refresh_library_flags(artist)

        assert artist.in_library is False
        assert artist.auto_download is True

    @pytest.mark.asyncio
    async def test_not_configured_skips(self, artist_service, mock_library_repo):
        mock_library_repo.is_configured.return_value = False
        artist = _make_artist(in_library=False)

        await artist_service._refresh_library_flags(artist)

        assert artist.in_library is False
        mock_library_repo.get_artist_mbids.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_release_in_library_flags_still_refreshed(
        self, artist_service, mock_library_repo
    ):
        mock_library_repo.get_library_mbids.return_value = {"album-1"}
        mock_library_repo.get_requested_mbids.return_value = {"album-2"}
        mock_library_repo.get_artist_mbids.return_value = set()

        from models.artist import ReleaseItem

        artist = ArtistInfo(
            name="Test",
            musicbrainz_id="aaa-bbb",
            albums=[
                ReleaseItem(id="album-1", title="A"),
                ReleaseItem(id="album-2", title="B"),
                ReleaseItem(id="album-3", title="C"),
            ],
        )

        await artist_service._refresh_library_flags(artist)

        assert artist.albums[0].in_library is True
        assert artist.albums[0].requested is False
        assert artist.albums[1].in_library is False
        assert artist.albums[1].requested is True
        assert artist.albums[2].in_library is False
        assert artist.albums[2].requested is False
