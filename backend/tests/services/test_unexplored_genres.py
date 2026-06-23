"""Tests for the Unexplored Genres section builder in DiscoverHomepageService."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from api.v1.schemas.discover import BecauseYouListenTo, DiscoverResponse
from api.v1.schemas.home import HomeSection, HomeArtist, HomeGenre
from api.v1.schemas.settings import (
    ListenBrainzConnectionSettings,
    LastFmConnectionSettings,
    PrimaryMusicSourceSettings,
)
from services.discover.homepage_service import (
    DiscoverHomepageService,
    UNEXPLORED_GENRES_THRESHOLD,
    UNEXPLORED_GENRES_MAX,
)
from services.discover.integration_helpers import IntegrationHelpers


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


def _make_genre_index(
    genres_for_artists: dict[str, list[str]] | None = None,
    genre_artist_counts: dict[str, int] | None = None,
    top_genres: list[tuple[str, int]] | None = None,
    underrepresented_genres: list[str] | None = None,
) -> AsyncMock:
    gi = AsyncMock()
    gi.get_genres_for_artists = AsyncMock(return_value=genres_for_artists or {})
    gi.get_genre_artist_counts = AsyncMock(return_value=genre_artist_counts or {})
    gi.get_top_genres = AsyncMock(return_value=top_genres or [])
    gi.get_underrepresented_genres = AsyncMock(return_value=underrepresented_genres or [])
    return gi


def _make_service(
    genre_index: AsyncMock | None = None,
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
        genre_index=genre_index,
    )


def _make_because_section(
    seed_name: str = "Radiohead",
    seed_mbid: str = "seed-mbid-1",
    artist_items: list[HomeArtist] | None = None,
) -> BecauseYouListenTo:
    items = artist_items or []
    return BecauseYouListenTo(
        seed_artist=seed_name,
        seed_artist_mbid=seed_mbid,
        section=HomeSection(
            title=f"Because You Listen To {seed_name}",
            type="artists",
            items=items,
            source="listenbrainz",
        ),
    )


# ---------------------------------------------------------------------------
# Test 1 - returns None when genre_index is None
# ---------------------------------------------------------------------------
class TestReturnsNoneWhenGenreIndexIsNone:
    @pytest.mark.asyncio
    async def test_returns_none_when_genre_index_is_none(self) -> None:
        service = _make_service(genre_index=None)
        result = await service._build_unexplored_genres([], [])
        assert result is None


# ---------------------------------------------------------------------------
# Test 2 - returns None when no because sections and no similar mbids
# ---------------------------------------------------------------------------
class TestReturnsNoneWhenEmpty:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_because_sections_and_no_similar_mbids(self) -> None:
        gi = _make_genre_index()
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], [])
        assert result is None


# ---------------------------------------------------------------------------
# Test 3 - returns section with underrepresented genres
# ---------------------------------------------------------------------------
class TestReturnsSectionWithUnderrepresentedGenres:
    @pytest.mark.asyncio
    async def test_returns_section_with_underrepresented_genres(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={
                "artist-1": ["Post-Punk", "Shoegaze"],
                "artist-2": ["Ambient"],
            },
            genre_artist_counts={"post-punk": 1, "shoegaze": 0, "ambient": 1},
            top_genres=[("rock", 50), ("pop", 30)],
        )
        service = _make_service(genre_index=gi)

        sections = [_make_because_section(artist_items=[])]
        similar = ["artist-1", "artist-2"]

        result = await service._build_unexplored_genres(sections, similar)
        assert result is not None
        assert len(result.items) == 3
        names = {item.name for item in result.items}
        assert "Post-Punk" in names
        assert "Shoegaze" in names
        assert "Ambient" in names


# ---------------------------------------------------------------------------
# Test 4 - filters genres at or above threshold
# ---------------------------------------------------------------------------
class TestFiltersGenresAtOrAboveThreshold:
    @pytest.mark.asyncio
    async def test_filters_genres_at_or_above_threshold(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={"a1": ["Rock", "Shoegaze"]},
            genre_artist_counts={"rock": 5, "shoegaze": 1},
            top_genres=[("pop", 30)],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is not None
        names = {item.name for item in result.items}
        assert "Rock" not in names
        assert "Shoegaze" in names


# ---------------------------------------------------------------------------
# Test 5 - excludes user top genres
# ---------------------------------------------------------------------------
class TestExcludesUserTopGenres:
    @pytest.mark.asyncio
    async def test_excludes_user_top_genres(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={"a1": ["Rock", "Ambient"]},
            genre_artist_counts={"rock": 0, "ambient": 0},
            top_genres=[("rock", 50)],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is not None
        names = {item.name for item in result.items}
        assert "Rock" not in names
        assert "Ambient" in names


# ---------------------------------------------------------------------------
# Test 6 - caps at 8 genres
# ---------------------------------------------------------------------------
class TestCapsAt8Genres:
    @pytest.mark.asyncio
    async def test_caps_at_8_genres(self) -> None:
        genre_names = [f"Genre-{i}" for i in range(12)]
        gi = _make_genre_index(
            genres_for_artists={"a1": genre_names},
            genre_artist_counts={},
            top_genres=[],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is not None
        assert len(result.items) == UNEXPLORED_GENRES_MAX


# ---------------------------------------------------------------------------
# Test 7 - section type is genres
# ---------------------------------------------------------------------------
class TestSectionTypeIsGenres:
    @pytest.mark.asyncio
    async def test_section_type_is_genres(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={"a1": ["Post-Punk"]},
            genre_artist_counts={},
            top_genres=[],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is not None
        assert result.type == "genres"


# ---------------------------------------------------------------------------
# Test 8 - section title
# ---------------------------------------------------------------------------
class TestSectionTitle:
    @pytest.mark.asyncio
    async def test_section_title(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={"a1": ["Post-Punk"]},
            genre_artist_counts={},
            top_genres=[],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is not None
        assert result.title == "Genres to Explore"


# ---------------------------------------------------------------------------
# Test 9 - fallback to get_underrepresented_genres
# ---------------------------------------------------------------------------
class TestFallbackToGetUnderrepresentedGenres:
    @pytest.mark.asyncio
    async def test_fallback_to_get_underrepresented_genres(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={"a1": ["Rock"]},
            genre_artist_counts={"rock": 5},
            top_genres=[],
            underrepresented_genres=["shoegaze", "ambient"],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is not None
        gi.get_underrepresented_genres.assert_awaited_once()
        names = {item.name for item in result.items}
        assert "Shoegaze" in names
        assert "Ambient" in names


# ---------------------------------------------------------------------------
# Test 10 - returns None when fallback also empty
# ---------------------------------------------------------------------------
class TestReturnsNoneWhenFallbackAlsoEmpty:
    @pytest.mark.asyncio
    async def test_returns_none_when_fallback_also_empty(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={"a1": ["Rock"]},
            genre_artist_counts={"rock": 5},
            top_genres=[],
            underrepresented_genres=[],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is None


# ---------------------------------------------------------------------------
# Test 11 - genre items have artist_count
# ---------------------------------------------------------------------------
class TestGenreItemsHaveArtistCount:
    @pytest.mark.asyncio
    async def test_genre_items_have_artist_count(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={"a1": ["Post-Punk", "Ambient"]},
            genre_artist_counts={"post-punk": 1, "ambient": 0},
            top_genres=[],
        )
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is not None
        counts_by_name = {item.name: item.artist_count for item in result.items}
        assert counts_by_name["Post-Punk"] == 1
        assert counts_by_name["Ambient"] == 0


# ---------------------------------------------------------------------------
# Test 12 - candidate MBIDs from because sections and similar
# ---------------------------------------------------------------------------
class TestCandidateMbidsFromBothSources:
    @pytest.mark.asyncio
    async def test_candidate_mbids_from_because_sections_and_similar(self) -> None:
        gi = _make_genre_index(
            genres_for_artists={
                "because-mbid": ["Shoegaze"],
                "similar-mbid": ["Ambient"],
            },
            genre_artist_counts={},
            top_genres=[],
        )
        service = _make_service(genre_index=gi)

        because = [_make_because_section(
            artist_items=[HomeArtist(name="Artist A", mbid="because-mbid")]
        )]
        similar = ["similar-mbid"]

        result = await service._build_unexplored_genres(because, similar)
        assert result is not None

        call_args = gi.get_genres_for_artists.call_args[0][0]
        assert "because-mbid" in call_args
        assert "similar-mbid" in call_args


# ---------------------------------------------------------------------------
# Test 13 - _has_meaningful_content with unexplored_genres
# ---------------------------------------------------------------------------
class TestHasMeaningfulContentWithUnexploredGenres:
    def test_has_meaningful_content_with_unexplored_genres(self) -> None:
        service = _make_service()
        section = HomeSection(title="Genres to Explore", type="genres", items=[
            HomeGenre(name="Ambient", artist_count=0),
        ])
        response = DiscoverResponse(unexplored_genres=section)
        assert service._has_meaningful_content(response) is True

    def test_has_meaningful_content_empty_response(self) -> None:
        service = _make_service()
        response = DiscoverResponse()
        assert service._has_meaningful_content(response) is False


# ---------------------------------------------------------------------------
# Test 14 - exception returns None
# ---------------------------------------------------------------------------
class TestExceptionReturnsNone:
    @pytest.mark.asyncio
    async def test_exception_returns_none(self) -> None:
        gi = _make_genre_index()
        gi.get_genres_for_artists = AsyncMock(side_effect=RuntimeError("db error"))
        service = _make_service(genre_index=gi)
        result = await service._build_unexplored_genres([], ["a1"])
        assert result is None
