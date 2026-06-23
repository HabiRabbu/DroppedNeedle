"""Tests for DiscoverRadioService and _build_radio_sections."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from api.v1.schemas.discover import (
    DiscoverQueueItemLight,
    DiscoverResponse,
    RadioRequest,
)
from api.v1.schemas.home import HomeAlbum, HomeSection
from api.v1.schemas.discovery import (
    DiscoveryAlbum,
    MoreByArtistResponse,
    SimilarAlbumsResponse,
)
from api.v1.schemas.settings import (
    ListenBrainzConnectionSettings,
    LastFmConnectionSettings,
    PrimaryMusicSourceSettings,
)
from models.album import AlbumInfo
from repositories.listenbrainz_models import ListenBrainzArtist, ListenBrainzReleaseGroup
from services.discover.homepage_service import DiscoverHomepageService
from services.discover.integration_helpers import IntegrationHelpers
from services.discover.radio_service import DiscoverRadioService


# ---- helpers ----

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


def _make_radio_service(
    lb_repo: AsyncMock | None = None,
    mb_repo: AsyncMock | None = None,
    mbid_svc: MagicMock | None = None,
    album_discovery: AsyncMock | None = None,
    genre_index: AsyncMock | None = None,
    integration: IntegrationHelpers | None = None,
) -> DiscoverRadioService:
    if lb_repo is None:
        lb_repo = AsyncMock()
    if mb_repo is None:
        mb_repo = AsyncMock()
    if mbid_svc is None:
        mbid_svc = MagicMock()
        mbid_svc.get_library_artist_mbids = AsyncMock(return_value=set())
        mbid_svc.normalize_mbid = MagicMock(side_effect=lambda x: x.strip().lower() if x and x.strip() else None)
        mbid_svc.make_queue_item = MagicMock(side_effect=lambda **kw: DiscoverQueueItemLight(
            release_group_mbid=kw["release_group_mbid"],
            album_name=kw["album_name"],
            artist_name=kw["artist_name"],
            artist_mbid=kw["artist_mbid"],
            recommendation_reason=kw.get("reason", ""),
        ))
    if album_discovery is None:
        album_discovery = AsyncMock()
    if genre_index is None:
        genre_index = AsyncMock()
    if integration is None:
        prefs = _make_prefs()
        integration = IntegrationHelpers(prefs)

    return DiscoverRadioService(
        lb_repo=lb_repo,
        mb_repo=mb_repo,
        mbid_svc=mbid_svc,
        album_discovery=album_discovery,
        genre_index=genre_index,
        integration=integration,
    )


def _make_homepage_service(
    genre_index: AsyncMock | None = None,
    cache: AsyncMock | None = None,
) -> DiscoverHomepageService:
    lb_repo = AsyncMock()
    jf_repo = AsyncMock()
    library_repo = AsyncMock()
    mb_repo = AsyncMock()
    prefs = _make_prefs()
    integration = IntegrationHelpers(prefs)
    mbid_resolution = MagicMock()

    return DiscoverHomepageService(
        listenbrainz_repo=lb_repo,
        jellyfin_repo=jf_repo,
        library_repo=library_repo,
        musicbrainz_repo=mb_repo,
        integration=integration,
        mbid_resolution=mbid_resolution,
        memory_cache=cache,
        genre_index=genre_index,
    )


# ==== DiscoverRadioService tests ====


class TestArtistSeed:
    @pytest.mark.asyncio
    @patch("services.discover.radio_service.round_robin_dedup_select")
    @patch("services.discover.radio_service.build_similar_artist_pools")
    async def test_artist_seed_returns_album_section(
        self, mock_pools, mock_select,
    ) -> None:
        items = _make_pool_items(3)
        mock_pools.return_value = [items]
        mock_select.return_value = items

        lb_repo = AsyncMock()
        lb_repo.get_artist_top_release_groups.return_value = [
            ListenBrainzReleaseGroup(
                release_group_mbid="rg-1",
                release_group_name="Album 1",
                artist_name="Test Artist",
                artist_mbids=["artist-1"],
                caa_id=None,
                caa_release_mbid=None,
                listen_count=10,
            )
        ]
        service = _make_radio_service(lb_repo=lb_repo)
        request = RadioRequest(seed_type="artist", seed_id="valid-mbid")

        result = await service.generate_radio(request)

        assert result.type == "albums"
        assert result.title.startswith("Radio: ")
        assert len(result.items) == 3
        assert all(isinstance(item, HomeAlbum) for item in result.items)

    @pytest.mark.asyncio
    async def test_artist_seed_unknown_mbid_raises_404(self) -> None:
        mbid_svc = MagicMock()
        mbid_svc.get_library_artist_mbids = AsyncMock(return_value=set())
        mbid_svc.normalize_mbid = MagicMock(return_value=None)

        service = _make_radio_service(mbid_svc=mbid_svc)
        request = RadioRequest(seed_type="artist", seed_id="bad-mbid")

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_radio(request)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("services.discover.radio_service.round_robin_dedup_select")
    @patch("services.discover.radio_service.build_similar_artist_pools")
    async def test_artist_seed_no_similar_returns_empty_section(
        self, mock_pools, mock_select,
    ) -> None:
        mock_pools.return_value = [[]]
        mock_select.return_value = []

        lb_repo = AsyncMock()
        lb_repo.get_artist_top_release_groups.return_value = []
        service = _make_radio_service(lb_repo=lb_repo)
        request = RadioRequest(seed_type="artist", seed_id="valid-mbid")

        result = await service.generate_radio(request)

        assert result.type == "albums"
        assert result.items == []


class TestAlbumSeed:
    @pytest.mark.asyncio
    async def test_album_seed_returns_merged_albums(self) -> None:
        mb_repo = AsyncMock()
        mb_repo.get_release_group.return_value = AlbumInfo(
            title="Seed Album",
            musicbrainz_id="seed-album-mbid",
            artist_name="Test Artist",
            artist_id="artist-123",
        )

        album_discovery = AsyncMock()
        album_discovery.get_similar_albums.return_value = SimilarAlbumsResponse(
            albums=[
                DiscoveryAlbum(musicbrainz_id="sim-1", title="Sim 1", artist_name="A1", artist_id="a1"),
                DiscoveryAlbum(musicbrainz_id="sim-2", title="Sim 2", artist_name="A2", artist_id="a2"),
            ]
        )
        album_discovery.get_more_by_artist.return_value = MoreByArtistResponse(
            albums=[
                DiscoveryAlbum(musicbrainz_id="more-1", title="More 1", artist_name="A1", artist_id="a1"),
                DiscoveryAlbum(musicbrainz_id="sim-1", title="Sim 1 dup", artist_name="A1", artist_id="a1"),
            ],
            artist_name="Test Artist",
        )

        service = _make_radio_service(mb_repo=mb_repo, album_discovery=album_discovery)
        request = RadioRequest(seed_type="album", seed_id="seed-album-mbid")

        result = await service.generate_radio(request)

        assert result.type == "albums"
        assert result.title == "Radio: Seed Album"
        mbids = [item.mbid for item in result.items if isinstance(item, HomeAlbum)]
        assert len(mbids) == 3
        assert len(set(mbids)) == 3  # all unique

    @pytest.mark.asyncio
    async def test_album_seed_unknown_mbid_raises_404(self) -> None:
        mbid_svc = MagicMock()
        mbid_svc.get_library_artist_mbids = AsyncMock(return_value=set())
        mbid_svc.normalize_mbid = MagicMock(return_value=None)

        service = _make_radio_service(mbid_svc=mbid_svc)
        request = RadioRequest(seed_type="album", seed_id="bad-mbid")

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_radio(request)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_album_seed_excludes_seed_album(self) -> None:
        mb_repo = AsyncMock()
        mb_repo.get_release_group.return_value = AlbumInfo(
            title="Seed Album",
            musicbrainz_id="seed-mbid",
            artist_name="A",
            artist_id="a-1",
        )

        album_discovery = AsyncMock()
        album_discovery.get_similar_albums.return_value = SimilarAlbumsResponse(
            albums=[
                DiscoveryAlbum(musicbrainz_id="seed-mbid", title="Should be excluded", artist_name="A", artist_id="a-1"),
                DiscoveryAlbum(musicbrainz_id="other-1", title="Other 1", artist_name="A", artist_id="a-1"),
            ]
        )
        album_discovery.get_more_by_artist.return_value = MoreByArtistResponse(albums=[], artist_name="A")

        service = _make_radio_service(mb_repo=mb_repo, album_discovery=album_discovery)
        request = RadioRequest(seed_type="album", seed_id="seed-mbid")

        result = await service.generate_radio(request)

        mbids = [item.mbid for item in result.items if isinstance(item, HomeAlbum)]
        assert "seed-mbid" not in mbids
        assert len(mbids) == 1


class TestGenreSeed:
    @pytest.mark.asyncio
    @patch("services.discover.radio_service.round_robin_dedup_select")
    @patch("services.discover.radio_service.build_similar_artist_pools")
    async def test_genre_seed_returns_album_section(
        self, mock_pools, mock_select,
    ) -> None:
        items = _make_pool_items(5)
        mock_pools.return_value = [items]
        mock_select.return_value = items

        genre_index = AsyncMock()
        genre_index.get_artists_for_genres.return_value = {
            "indie rock": ["mbid-1", "mbid-2", "mbid-3"]
        }

        service = _make_radio_service(genre_index=genre_index)
        request = RadioRequest(seed_type="genre", seed_id="indie rock")

        result = await service.generate_radio(request)

        assert result.type == "albums"
        assert result.title == "Radio: Indie Rock"
        assert len(result.items) == 5

    @pytest.mark.asyncio
    async def test_genre_seed_unknown_tag_raises_422(self) -> None:
        genre_index = AsyncMock()
        genre_index.get_artists_for_genres.return_value = {}

        service = _make_radio_service(genre_index=genre_index)
        request = RadioRequest(seed_type="genre", seed_id="nonexistent genre")

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_radio(request)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    @patch("services.discover.radio_service.build_similar_artist_pools")
    async def test_genre_seed_samples_up_to_5_artists(
        self, mock_pools,
    ) -> None:
        mock_pools.return_value = [[] for _ in range(5)]

        genre_index = AsyncMock()
        genre_index.get_artists_for_genres.return_value = {
            "rock": [f"mbid-{i}" for i in range(10)]
        }

        service = _make_radio_service(genre_index=genre_index)
        request = RadioRequest(seed_type="genre", seed_id="rock")

        await service.generate_radio(request)

        call_args = mock_pools.call_args
        seeds_passed = call_args[0][0]
        assert len(seeds_passed) == 5


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_empty_seed_id_raises_400(self) -> None:
        service = _make_radio_service()
        request = RadioRequest(seed_type="artist", seed_id="")

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_radio(request)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_seed_id_raises_400(self) -> None:
        service = _make_radio_service()
        request = RadioRequest(seed_type="artist", seed_id="   ")

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_radio(request)
        assert exc_info.value.status_code == 400


class TestCountAndSource:
    @pytest.mark.asyncio
    @patch("services.discover.radio_service.round_robin_dedup_select")
    @patch("services.discover.radio_service.build_similar_artist_pools")
    async def test_count_parameter_respected(
        self, mock_pools, mock_select,
    ) -> None:
        items = _make_pool_items(10)
        mock_pools.return_value = [items]
        mock_select.return_value = items[:5]

        lb_repo = AsyncMock()
        lb_repo.get_artist_top_release_groups.return_value = []
        service = _make_radio_service(lb_repo=lb_repo)
        request = RadioRequest(seed_type="artist", seed_id="valid-mbid", count=5)

        result = await service.generate_radio(request)

        assert len(result.items) <= 5
        mock_select.assert_called_once_with(mock_pools.return_value, 5)

    @pytest.mark.asyncio
    @patch("services.discover.radio_service.round_robin_dedup_select")
    @patch("services.discover.radio_service.build_similar_artist_pools")
    async def test_source_resolution(
        self, mock_pools, mock_select,
    ) -> None:
        mock_pools.return_value = [[]]
        mock_select.return_value = []

        lb_repo = AsyncMock()
        lb_repo.get_artist_top_release_groups.return_value = []
        service = _make_radio_service(lb_repo=lb_repo)
        request = RadioRequest(seed_type="artist", seed_id="valid-mbid", source=None)

        result = await service.generate_radio(request)

        assert result.source == "listenbrainz"


# ==== DiscoverHomepageService._build_radio_sections tests ====


class TestBuildRadioSections:
    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_build_radio_sections_returns_sections_for_seeds(
        self, mock_pools, mock_select,
    ) -> None:
        items = _make_pool_items(3)
        mock_pools.return_value = [items]
        mock_select.return_value = items

        service = _make_homepage_service()
        seeds = [
            ListenBrainzArtist(artist_name=f"Seed {i}", artist_mbids=[f"mbid-{i}"], listen_count=10)
            for i in range(3)
        ]

        result = await service._build_radio_sections(seeds, set(), "listenbrainz")

        assert len(result) == 3
        assert all(isinstance(s, HomeSection) for s in result)
        assert all(s.type == "albums" for s in result)
        assert all(s.title.startswith("Radio: ") for s in result)

    @pytest.mark.asyncio
    @patch("services.discover.homepage_service.round_robin_dedup_select")
    @patch("services.discover.homepage_service.build_similar_artist_pools")
    async def test_build_radio_sections_isolates_failures(
        self, mock_pools, mock_select,
    ) -> None:
        items = _make_pool_items(2)
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("LB API error")
            return [items]

        mock_pools.side_effect = side_effect
        mock_select.return_value = items

        service = _make_homepage_service()
        seeds = [
            ListenBrainzArtist(artist_name=f"Seed {i}", artist_mbids=[f"mbid-{i}"], listen_count=10)
            for i in range(3)
        ]

        result = await service._build_radio_sections(seeds, set(), "listenbrainz")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_build_radio_sections_empty_seeds(self) -> None:
        service = _make_homepage_service()
        result = await service._build_radio_sections([], set(), "listenbrainz")
        assert result == []


class TestHasMeaningfulContentWithRadioSections:
    def test_has_meaningful_content_with_radio_sections(self) -> None:
        service = _make_homepage_service()
        response = DiscoverResponse(
            radio_sections=[
                HomeSection(
                    title="Radio: Test",
                    type="albums",
                    items=[HomeAlbum(name="Album", mbid="mbid-1")],
                )
            ]
        )
        assert service._has_meaningful_content(response) is True

    def test_has_meaningful_content_empty_response(self) -> None:
        service = _make_homepage_service()
        response = DiscoverResponse()
        assert service._has_meaningful_content(response) is False


class TestGenerateRadioFallbackWhenSourceDisabled:
    @pytest.mark.asyncio
    async def test_generate_radio_returns_fallback_section_when_source_disabled(self) -> None:
        prefs = _make_prefs(lb_enabled=False, lfm_enabled=False)
        integration = IntegrationHelpers(prefs)
        service = _make_radio_service(integration=integration)
        request = RadioRequest(seed_type="artist", seed_id="valid-mbid", source="listenbrainz")

        result = await service.generate_radio(request)

        assert result.items == []
        assert result.fallback_message == "listenbrainz is not enabled"
        assert result.source == "listenbrainz"
        assert result.type == "albums"
