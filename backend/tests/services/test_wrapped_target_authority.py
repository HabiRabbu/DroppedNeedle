from unittest.mock import AsyncMock

import pytest

from api.v1.schemas.home import (
    HomeAlbum,
    HomeArtist,
    PopularAlbumsRangeResponse,
    TrendingArtistsRangeResponse,
)
from services.wrapped_service import WrappedService


def _charts(artist: str, album: str) -> AsyncMock:
    charts = AsyncMock()
    charts.get_trending_artists_by_range.return_value = TrendingArtistsRangeResponse(
        range_key="this_year",
        label="This year",
        items=[HomeArtist(name=artist, mbid=f"{artist}-id", listen_count=4)],
    )
    charts.get_popular_albums_by_range.return_value = PopularAlbumsRangeResponse(
        range_key="this_year",
        label="This year",
        items=[
            HomeAlbum(
                name=album,
                artist_name=artist,
                mbid=f"{album}-id",
                listen_count=3,
            )
        ],
    )
    return charts


@pytest.mark.asyncio
async def test_target_wrapped_uses_its_injected_target_charts() -> None:
    auth = AsyncMock()
    auth.list_users.return_value = []
    client_factory = AsyncMock()
    legacy = WrappedService(auth, client_factory, _charts("Legacy", "Legacy Album"))
    target = WrappedService(auth, client_factory, _charts("Target", "Target Album"))

    legacy_result = await legacy.get_server_wrapped()
    target_result = await target.get_server_wrapped()

    assert legacy_result.top_artist_sitewide.name == "Legacy"
    assert target_result.top_artist_sitewide.name == "Target"
    assert legacy_result.top_album_sitewide.name == "Legacy Album"
    assert target_result.top_album_sitewide.name == "Target Album"
