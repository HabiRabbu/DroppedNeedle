from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.library import LibraryGroupedAlbum, LibraryGroupedArtist
from core.exceptions import ExternalServiceError
from services.library_service import LibraryService


def _make_service() -> tuple[LibraryService, MagicMock]:
    library_repo = MagicMock()
    library_db = MagicMock()
    cover_repo = MagicMock()
    preferences_service = MagicMock()

    service = LibraryService(
        library_repo=library_repo,
        library_db=library_db,
        cover_repo=cover_repo,
        preferences_service=preferences_service,
    )
    return service, library_repo


@pytest.mark.asyncio
async def test_get_library_grouped_returns_typed_data():
    service, library_repo = _make_service()
    expected = [
        LibraryGroupedArtist(
            artist="Artist A",
            albums=[LibraryGroupedAlbum(title="Album A", year=2024)],
        )
    ]
    library_repo.get_library_grouped = AsyncMock(return_value=expected)

    grouped = await service.get_library_grouped()

    assert len(grouped) == 1
    assert grouped[0].artist == "Artist A"
    assert grouped[0].albums[0].title == "Album A"


@pytest.mark.asyncio
async def test_get_library_grouped_wraps_errors():
    service, library_repo = _make_service()
    library_repo.get_library_grouped = AsyncMock(side_effect=RuntimeError("unavailable"))

    with pytest.raises(ExternalServiceError):
        await service.get_library_grouped()
