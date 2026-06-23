"""Tests for playlist-seeded discovery: PlaylistService.analyse_playlist_profile
and DiscoverHomepageService.build_playlist_suggestions."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from api.v1.schemas.discover import (
    DiscoverQueueItemLight,
    PlaylistProfile,
    PlaylistSuggestionsRequest,
    PlaylistSuggestionsResponse,
)
from api.v1.schemas.home import HomeAlbum, HomeSection
from api.v1.schemas.settings import (
    ListenBrainzConnectionSettings,
    LastFmConnectionSettings,
    PrimaryMusicSourceSettings,
)
from repositories.listenbrainz_models import ListenBrainzArtist
from repositories.playlist_repository import PlaylistRecord, PlaylistTrackRecord
from services.discover.facade import DiscoverService
from services.discover.homepage_service import DiscoverHomepageService
from services.discover.integration_helpers import IntegrationHelpers
from services.playlist_service import PlaylistService


def _make_lb_settings(
    enabled: bool = True, username: str = "lbuser",
) -> ListenBrainzConnectionSettings:
    return ListenBrainzConnectionSettings(
        user_token="tok", username=username, enabled=enabled,
    )


def _make_lfm_settings(
    enabled: bool = True, username: str = "lfmuser",
) -> LastFmConnectionSettings:
    return LastFmConnectionSettings(
        api_key="key", shared_secret="secret", session_key="sk",
        username=username, enabled=enabled,
    )


def _make_prefs(
    lb_enabled: bool = True,
    lfm_enabled: bool = False,
    primary_source: str = "listenbrainz",
) -> MagicMock:
    prefs = MagicMock()
    prefs.get_listenbrainz_connection.return_value = _make_lb_settings(enabled=lb_enabled)
    prefs.get_lastfm_connection.return_value = _make_lfm_settings(enabled=lfm_enabled)
    prefs.is_lastfm_enabled.return_value = lfm_enabled
    prefs.get_primary_music_source.return_value = PrimaryMusicSourceSettings(source=primary_source)

    jf_settings = MagicMock()
    jf_settings.enabled = False
    jf_settings.jellyfin_url = ""
    jf_settings.api_key = ""
    prefs.get_jellyfin_connection.return_value = jf_settings

    download_client = MagicMock()
    download_client.enabled = False
    download_client.url = ""
    prefs.get_download_client_settings.return_value = download_client

    yt = MagicMock()
    yt.enabled = False
    yt.api_key = ""
    prefs.get_youtube_connection.return_value = yt

    lf = MagicMock()
    lf.enabled = False
    lf.music_path = ""
    prefs.get_local_files_connection.return_value = lf

    adv = MagicMock()
    adv.discover_queue_size = 10
    adv.discover_queue_ttl = 3600
    adv.discover_queue_seed_artists = 3
    adv.discover_queue_wildcard_slots = 2
    adv.discover_queue_similar_artists_limit = 15
    adv.discover_queue_albums_per_similar = 3
    adv.discover_queue_enrich_ttl = 3600
    adv.discover_queue_lastfm_mbid_max_lookups = 10
    prefs.get_advanced_settings.return_value = adv

    return prefs


def _make_pool_items(count: int, prefix: str = "album") -> list[DiscoverQueueItemLight]:
    return [
        DiscoverQueueItemLight(
            release_group_mbid=f"rg-{prefix}-{i}",
            album_name=f"{prefix.title()} {i}",
            artist_name=f"Artist {i}",
            artist_mbid=f"artist-{prefix}-{i}",
            recommendation_reason="Similar to seed",
        )
        for i in range(count)
    ]


def _make_track_record(
    artist_id: str | None = None,
    track_name: str = "Track",
    playlist_id: str = "pl-1",
) -> PlaylistTrackRecord:
    return PlaylistTrackRecord(
        id="t-1",
        playlist_id=playlist_id,
        position=0,
        track_name=track_name,
        artist_name="Artist",
        album_name="Album",
        album_id=None,
        artist_id=artist_id,
        track_source_id=None,
        cover_url=None,
        source_type="",
        available_sources=None,
        format=None,
        track_number=None,
        disc_number=None,
        duration=None,
        created_at="2024-01-01",
    )


_REQ = SimpleNamespace(id="owner", role="user")


def _make_playlist_record(playlist_id: str = "pl-1") -> PlaylistRecord:
    return PlaylistRecord(
        id=playlist_id,
        name="Test Playlist",
        cover_image_path=None,
        created_at="2024-01-01",
        updated_at="2024-01-01",
        user_id="owner",
    )


def _make_playlist_service(
    repo: AsyncMock | None = None,
    genre_index: AsyncMock | None = None,
) -> PlaylistService:
    if repo is None:
        repo = MagicMock()
    service = PlaylistService.__new__(PlaylistService)
    service._repo = repo
    service._genre_index = genre_index
    service._cache = None
    return service


def _make_homepage_service(
    genre_index: AsyncMock | None = None,
    cache: AsyncMock | None = None,
    lb_enabled: bool = True,
    lfm_enabled: bool = False,
    primary_source: str = "listenbrainz",
    lastfm_repo: AsyncMock | None = None,
) -> DiscoverHomepageService:
    lb_repo = AsyncMock()
    jf_repo = AsyncMock()
    library_repo = AsyncMock()
    mb_repo = AsyncMock()
    prefs = _make_prefs(lb_enabled=lb_enabled, lfm_enabled=lfm_enabled, primary_source=primary_source)
    integration = IntegrationHelpers(prefs)
    mbid_resolution = MagicMock()

    # per-user identity is resolved from the factory, not global preferences
    factory = MagicMock()
    factory.resolve_listenbrainz = AsyncMock(return_value=lb_repo if lb_enabled else None)
    factory.resolve_lastfm = AsyncMock(return_value=(lastfm_repo or AsyncMock()) if lfm_enabled else None)
    factory.resolve_listenbrainz_username = AsyncMock(return_value="lbuser" if lb_enabled else None)
    factory.resolve_lastfm_username = AsyncMock(return_value="lfmuser" if lfm_enabled else None)
    prefs_store = MagicMock()
    prefs_store.get = AsyncMock(return_value=SimpleNamespace(primary_music_source=primary_source))

    return DiscoverHomepageService(
        listenbrainz_repo=lb_repo,
        jellyfin_repo=jf_repo,
        library_repo=library_repo,
        musicbrainz_repo=mb_repo,
        integration=integration,
        mbid_resolution=mbid_resolution,
        memory_cache=cache,
        genre_index=genre_index,
        lastfm_repo=lastfm_repo,
        client_factory=factory,
        listening_prefs_store=prefs_store,
    )


class TestAnalyseProfileReturnsNoneForUnknownPlaylist:
    @pytest.mark.asyncio
    async def test_unknown_playlist_returns_none(self) -> None:
        repo = AsyncMock()
        repo.get_playlist.return_value = None
        service = _make_playlist_service(repo=repo)

        result = await service.analyse_playlist_profile("nonexistent", _REQ)

        assert result is None


class TestAnalyseProfilePrivateNonOwnerReturnsNone:
    @pytest.mark.asyncio
    async def test_private_playlist_of_another_user_returns_none(self) -> None:
        # D4: a non-owner must not learn a private playlist's existence or artists
        repo = AsyncMock()
        record = _make_playlist_record()
        record.user_id = "someone-else"
        record.is_public = False
        repo.get_playlist.return_value = record
        repo.get_tracks.return_value = [_make_track_record(artist_id="mbid-a")]
        service = _make_playlist_service(repo=repo)

        result = await service.analyse_playlist_profile("pl-1", _REQ)

        assert result is None
        repo.get_tracks.assert_not_called()


class TestAnalyseProfilePublicNonOwnerReturnsProfile:
    @pytest.mark.asyncio
    async def test_public_playlist_of_another_user_returns_profile(self) -> None:
        repo = AsyncMock()
        record = _make_playlist_record()
        record.user_id = "someone-else"
        record.is_public = True
        repo.get_playlist.return_value = record
        repo.get_tracks.return_value = [_make_track_record(artist_id="mbid-a")]
        service = _make_playlist_service(repo=repo)

        result = await service.analyse_playlist_profile("pl-1", _REQ)

        assert result is not None
        assert result.artist_mbids == ["mbid-a"]


class TestAnalyseProfileEmptyArtistMbids:
    @pytest.mark.asyncio
    async def test_no_artist_ids_returns_empty_list(self) -> None:
        repo = AsyncMock()
        repo.get_playlist.return_value = _make_playlist_record()
        tracks = [
            _make_track_record(artist_id=None),
            _make_track_record(artist_id=None),
        ]
        repo.get_tracks.return_value = tracks
        service = _make_playlist_service(repo=repo)

        result = await service.analyse_playlist_profile("pl-1", _REQ)

        assert result is not None
        assert result.artist_mbids == []
        assert result.track_count == 2


class TestAnalyseProfileExtractsUniqueArtistMbids:
    @pytest.mark.asyncio
    async def test_deduplicates_artist_ids(self) -> None:
        repo = AsyncMock()
        repo.get_playlist.return_value = _make_playlist_record()
        tracks = [
            _make_track_record(artist_id="mbid-a"),
            _make_track_record(artist_id="mbid-a"),
            _make_track_record(artist_id="mbid-b"),
        ]
        repo.get_tracks.return_value = tracks
        service = _make_playlist_service(repo=repo)

        result = await service.analyse_playlist_profile("pl-1", _REQ)

        assert result is not None
        assert sorted(result.artist_mbids) == ["mbid-a", "mbid-b"]


class TestAnalyseProfileBuildsGenreDistribution:
    @pytest.mark.asyncio
    async def test_genre_distribution_populated(self) -> None:
        repo = AsyncMock()
        repo.get_playlist.return_value = _make_playlist_record()
        repo.get_tracks.return_value = [
            _make_track_record(artist_id="mbid-a"),
        ]
        genre_index = AsyncMock()
        genre_index.get_genres_for_artists.return_value = {
            "mbid-a": ["rock", "alternative"],
        }
        service = _make_playlist_service(repo=repo, genre_index=genre_index)

        result = await service.analyse_playlist_profile("pl-1", _REQ)

        assert result is not None
        assert result.genre_distribution == {"mbid-a": ["rock", "alternative"]}


class TestAnalyseProfileNoGenreIndex:
    @pytest.mark.asyncio
    async def test_no_genre_index_returns_empty_distribution(self) -> None:
        repo = AsyncMock()
        repo.get_playlist.return_value = _make_playlist_record()
        repo.get_tracks.return_value = [
            _make_track_record(artist_id="mbid-a"),
        ]
        service = _make_playlist_service(repo=repo, genre_index=None)

        result = await service.analyse_playlist_profile("pl-1", _REQ)

        assert result is not None
        assert result.genre_distribution == {}


class TestFacadePlaylistNotFoundRaises404:
    @pytest.mark.asyncio
    async def test_raises_404(self) -> None:
        playlist_service = AsyncMock()
        playlist_service.analyse_playlist_profile.return_value = None
        homepage = AsyncMock()

        facade = DiscoverService.__new__(DiscoverService)
        facade._playlist_service = playlist_service
        facade._homepage = homepage
        facade._integration = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await facade.get_playlist_suggestions(
                PlaylistSuggestionsRequest(playlist_id="missing"), _REQ,
            )
        assert exc_info.value.status_code == 404


class TestFacadeEmptyProfileRaises422:
    @pytest.mark.asyncio
    async def test_raises_422(self) -> None:
        playlist_service = AsyncMock()
        playlist_service.analyse_playlist_profile.return_value = PlaylistProfile(
            artist_mbids=[], track_count=5,
        )
        homepage = AsyncMock()

        facade = DiscoverService.__new__(DiscoverService)
        facade._playlist_service = playlist_service
        facade._homepage = homepage
        facade._integration = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await facade.get_playlist_suggestions(
                PlaylistSuggestionsRequest(playlist_id="pl-1"), _REQ,
            )
        assert exc_info.value.status_code == 422


class TestFacadeDelegatesToHomepageBuild:
    @pytest.mark.asyncio
    async def test_delegates_and_returns_response(self) -> None:
        profile = PlaylistProfile(artist_mbids=["mbid-a"], track_count=3)
        section = HomeSection(title="Suggestions for your playlist", type="albums")

        playlist_service = AsyncMock()
        playlist_service.analyse_playlist_profile.return_value = profile
        homepage = AsyncMock()
        homepage.build_playlist_suggestions.return_value = section

        facade = DiscoverService.__new__(DiscoverService)
        facade._playlist_service = playlist_service
        facade._homepage = homepage
        facade._integration = MagicMock()

        result = await facade.get_playlist_suggestions(
            PlaylistSuggestionsRequest(playlist_id="pl-1"), _REQ,
        )
        assert isinstance(result, PlaylistSuggestionsResponse)
        assert result.playlist_id == "pl-1"
        assert result.profile == profile
        assert result.suggestions == section
        homepage.build_playlist_suggestions.assert_awaited_once()


class TestBuildSuggestionsReturnsAlbumSection:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_returns_album_section(self, mock_pools, mock_select) -> None:
        items = _make_pool_items(3)
        mock_pools.return_value = [items]
        mock_select.return_value = items

        service = _make_homepage_service()
        profile = PlaylistProfile(artist_mbids=["a-1", "a-2", "a-3"], track_count=10)

        result = await service.build_playlist_suggestions("u1", profile)

        assert result.type == "albums"
        assert result.title == "Suggestions for your playlist"
        assert len(result.items) == 3
        assert all(isinstance(a, HomeAlbum) for a in result.items)


class TestBuildSuggestionsUsesGenrePool:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.discover_by_genres")
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_calls_discover_by_genres(
        self, mock_pools, mock_select, mock_genre_discover,
    ) -> None:
        mock_pools.return_value = [_make_pool_items(2)]
        mock_genre_discover.return_value = _make_pool_items(2, prefix="genre")
        mock_select.return_value = _make_pool_items(4)

        service = _make_homepage_service()
        profile = PlaylistProfile(
            artist_mbids=["a-1"],
            genre_distribution={"a-1": ["rock", "jazz"]},
            track_count=5,
        )

        await service.build_playlist_suggestions("u1", profile)

        mock_genre_discover.assert_awaited_once()
        call_args = mock_genre_discover.call_args
        assert "rock" in call_args.args[0] or "jazz" in call_args.args[0]


class TestBuildSuggestionsEmptyResultsReturnsFallback:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_empty_results_returns_fallback(self, mock_pools, mock_select) -> None:
        mock_pools.return_value = [[]]
        mock_select.return_value = []

        service = _make_homepage_service()
        profile = PlaylistProfile(artist_mbids=["a-1"], track_count=1)

        result = await service.build_playlist_suggestions("u1", profile)

        assert result.items == []
        assert result.fallback_message is not None
        assert "not enough suggestions" in result.fallback_message.lower()


class TestBuildSuggestionsCapsAtCount:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_caps_at_count(self, mock_pools, mock_select) -> None:
        items = _make_pool_items(5)
        mock_pools.return_value = [items]
        mock_select.return_value = items

        service = _make_homepage_service()
        profile = PlaylistProfile(artist_mbids=["a-1"], track_count=10)

        result = await service.build_playlist_suggestions("u1", profile, count=5)

        mock_select.assert_called_once_with(mock_pools.return_value, 5)
        assert len(result.items) <= 5


class TestBuildSuggestionsExcludesPlaylistArtists:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_excluded_mbids_matches_profile(self, mock_pools, mock_select) -> None:
        mock_pools.return_value = [[]]
        mock_select.return_value = _make_pool_items(1)

        service = _make_homepage_service()
        profile = PlaylistProfile(artist_mbids=["a-1", "a-2"], track_count=5)

        await service.build_playlist_suggestions("u1", profile)

        call_kwargs = mock_pools.call_args
        assert call_kwargs.kwargs["excluded_mbids"] == {"a-1", "a-2"}


class TestBuildSuggestionsSourceResolution:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_source_resolution(self, mock_pools, mock_select) -> None:
        mock_pools.return_value = [_make_pool_items(1)]
        mock_select.return_value = _make_pool_items(1)

        service = _make_homepage_service()
        profile = PlaylistProfile(artist_mbids=["a-1"], track_count=5)

        result = await service.build_playlist_suggestions("u1", profile, source=None)

        assert result.source is not None


class TestBuildSuggestionsDisabledSourceReturnsFallback:
    @pytest.mark.asyncio
    async def test_disabled_source_returns_fallback(self) -> None:
        service = _make_homepage_service(lb_enabled=False, lfm_enabled=False)
        profile = PlaylistProfile(artist_mbids=["a-1"], track_count=5)

        result = await service.build_playlist_suggestions(
            "u1", profile, source="listenbrainz",
        )

        assert result.items == []
        assert result.fallback_message is not None
        assert "isn't set up yet" in result.fallback_message.lower()

class TestBuildSuggestionsDisabledSourceNoneReturnsFallback:
    """Regression: when source=None and both providers disabled, fallback must trigger."""

    @pytest.mark.asyncio
    async def test_source_none_both_disabled_returns_fallback(self) -> None:
        service = _make_homepage_service(lb_enabled=False, lfm_enabled=False)
        profile = PlaylistProfile(artist_mbids=["a-1"], track_count=5)

        result = await service.build_playlist_suggestions("u1", profile, source=None)

        assert result.items == []
        assert result.fallback_message is not None
        assert "isn't set up yet" in result.fallback_message.lower()


class TestBuildSuggestionsLastfmPathCallsLastfmRepo:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools_lastfm")
    async def test_lastfm_source_uses_lastfm_pool_builder(
        self, mock_lfm_pools, mock_select,
    ) -> None:
        items = _make_pool_items(3, prefix="lfm")
        mock_lfm_pools.return_value = [items]
        mock_select.return_value = items

        lfm_repo = AsyncMock()
        service = _make_homepage_service(
            lb_enabled=True, lfm_enabled=True,
            primary_source="lastfm", lastfm_repo=lfm_repo,
        )
        profile = PlaylistProfile(artist_mbids=["a-1", "a-2", "a-3"], track_count=10)

        result = await service.build_playlist_suggestions("u1", profile, source="lastfm")

        mock_lfm_pools.assert_awaited_once()
        call_kwargs = mock_lfm_pools.call_args
        assert call_kwargs.kwargs["lfm_repo"] is lfm_repo
        assert result.source == "lastfm"
        assert len(result.items) == 3

    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_listenbrainz_source_uses_lb_pool_builder(
        self, mock_lb_pools, mock_select,
    ) -> None:
        items = _make_pool_items(3, prefix="lb")
        mock_lb_pools.return_value = [items]
        mock_select.return_value = items

        lfm_repo = AsyncMock()
        service = _make_homepage_service(
            lb_enabled=True, lfm_enabled=True,
            primary_source="listenbrainz", lastfm_repo=lfm_repo,
        )
        profile = PlaylistProfile(artist_mbids=["a-1", "a-2", "a-3"], track_count=10)

        result = await service.build_playlist_suggestions("u1", profile, source="listenbrainz")

        mock_lb_pools.assert_awaited_once()
        call_kwargs = mock_lb_pools.call_args
        assert call_kwargs.kwargs["lb_repo"] is service._lb_repo
        assert result.source == "listenbrainz"
