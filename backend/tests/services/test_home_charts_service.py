import pytest
from unittest.mock import AsyncMock, MagicMock, call

from api.v1.schemas.settings import (
    LastFmConnectionSettings,
    ListenBrainzConnectionSettings,
    PrimaryMusicSourceSettings,
)
from services.home_charts_service import HomeChartsService


def _make_prefs(
    lb_enabled: bool = True,
    lfm_enabled: bool = True,
    lfm_username: str = "lfmuser",
    primary_source: str = "lastfm",
) -> MagicMock:
    prefs = MagicMock()
    lb_settings = ListenBrainzConnectionSettings(
        user_token="tok", username="lbuser", enabled=lb_enabled
    )
    prefs.get_listenbrainz_connection.return_value = lb_settings

    lfm_settings = LastFmConnectionSettings(
        api_key="key",
        shared_secret="secret",
        session_key="sk",
        username=lfm_username,
        enabled=lfm_enabled,
    )
    prefs.get_lastfm_connection.return_value = lfm_settings
    prefs.is_lastfm_enabled.return_value = lfm_enabled
    prefs.get_primary_music_source.return_value = PrimaryMusicSourceSettings(source=primary_source)
    return prefs


def _make_service(
    lb_enabled: bool = True,
    lfm_enabled: bool = True,
    lfm_username: str = "lfmuser",
    primary_source: str = "lastfm",
) -> tuple[HomeChartsService, AsyncMock, AsyncMock]:
    lb_repo = AsyncMock()
    lb_repo.get_sitewide_top_artists = AsyncMock(return_value=[])
    lb_repo.get_sitewide_top_release_groups = AsyncMock(return_value=[])

    lfm_repo = AsyncMock()
    lfm_repo.get_global_top_artists = AsyncMock(return_value=[])
    lfm_repo.get_user_top_albums = AsyncMock(return_value=[])

    library_repo = AsyncMock()
    library_repo.get_library = AsyncMock(return_value=[])
    library_repo.get_artists_from_library = AsyncMock(return_value=[])

    mb_repo = AsyncMock()
    prefs = _make_prefs(
        lb_enabled=lb_enabled,
        lfm_enabled=lfm_enabled,
        lfm_username=lfm_username,
        primary_source=primary_source,
    )

    service = HomeChartsService(
        listenbrainz_repo=lb_repo,
        library_repo=library_repo,
        musicbrainz_repo=mb_repo,
        lastfm_repo=lfm_repo,
        preferences_service=prefs,
    )
    return service, lb_repo, lfm_repo


class TestPopularAlbumsLastFmMissingUsername:
    @pytest.mark.asyncio
    async def test_returns_empty_when_username_missing(self):
        """When Last.fm is enabled but username is empty, should return empty response."""
        service, _, lfm_repo = _make_service(
            lfm_enabled=True, lfm_username="", primary_source="lastfm"
        )
        result = await service.get_popular_albums(limit=10, source="lastfm")
        lfm_repo.get_user_top_albums.assert_not_awaited()
        assert result.all_time.featured is None
        assert result.all_time.items == []
        assert result.all_time.total_count == 0

    @pytest.mark.asyncio
    async def test_returns_empty_when_lastfm_disabled(self):
        """When Last.fm is disabled, should return empty response."""
        service, _, lfm_repo = _make_service(
            lfm_enabled=False, lfm_username="user", primary_source="lastfm"
        )
        result = await service._get_popular_albums_lastfm(limit=10)
        lfm_repo.get_user_top_albums.assert_not_awaited()
        assert result.all_time.total_count == 0

    @pytest.mark.asyncio
    async def test_calls_api_when_username_present(self):
        """When Last.fm is enabled with a username, should call the API."""
        service, _, lfm_repo = _make_service(
            lfm_enabled=True, lfm_username="validuser", primary_source="lastfm"
        )
        await service.get_popular_albums(limit=10, source="lastfm")
        assert lfm_repo.get_user_top_albums.await_count == 4
        lfm_repo.get_user_top_albums.assert_has_awaits(
            [
                call("validuser", period="7day", limit=11),
                call("validuser", period="1month", limit=11),
                call("validuser", period="12month", limit=11),
                call("validuser", period="overall", limit=11),
            ],
            any_order=True,
        )

    @pytest.mark.asyncio
    async def test_range_endpoint_uses_source_specific_lastfm_period(self):
        service, _, lfm_repo = _make_service(
            lfm_enabled=True, lfm_username="validuser", primary_source="lastfm"
        )
        await service.get_popular_albums_by_range(
            range_key="this_year",
            limit=5,
            offset=0,
            source="lastfm",
        )
        lfm_repo.get_user_top_albums.assert_awaited_once_with(
            "validuser", period="12month", limit=6
        )
