from unittest.mock import AsyncMock, call

import pytest

from api.v1.schemas.discover import DiscoverResponse
from api.v1.schemas.home import GenreArtwork, HomeGenre, HomeResponse, HomeSection
from services.discover.homepage_service import DiscoverHomepageService
from services.home.facade import HomeService


@pytest.mark.asyncio
async def test_home_and_discover_use_the_same_batched_artwork_projection() -> None:
    projection = {"Latin": GenreArtwork(kind="gradient", version="v2:4:e3b0c44298fc")}
    artwork_service = AsyncMock()
    artwork_service.get_artwork_batch.return_value = projection
    genre_section = HomeSection(
        title="Browse Genres", type="genres", items=[HomeGenre(name="Latin")]
    )
    home = object.__new__(HomeService)
    home._genre_artwork = artwork_service
    discover = object.__new__(DiscoverHomepageService)
    discover._genre_artwork = artwork_service
    home_response = HomeResponse(genre_list=genre_section)
    discover_response = DiscoverResponse(genre_list=genre_section)

    await home._apply_genre_artwork(home_response)
    await discover._apply_genre_artwork(discover_response)

    assert home_response.genre_artwork == projection
    assert discover_response.genre_artwork == projection
    assert artwork_service.get_artwork_batch.await_args_list == [
        call(["Latin"]),
        call(["Latin"]),
    ]
