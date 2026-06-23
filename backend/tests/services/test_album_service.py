from unittest.mock import AsyncMock, MagicMock

import pytest

from services.album_service import AlbumService


def _make_service() -> tuple[AlbumService, MagicMock, MagicMock]:
    library_repo = MagicMock()
    mb_repo = MagicMock()
    library_db = MagicMock()
    memory_cache = MagicMock()
    disk_cache = MagicMock()
    preferences_service = MagicMock()
    audiodb_image_service = MagicMock()

    service = AlbumService(
        library_repo=library_repo,
        mb_repo=mb_repo,
        library_db=library_db,
        memory_cache=memory_cache,
        disk_cache=disk_cache,
        preferences_service=preferences_service,
        audiodb_image_service=audiodb_image_service,
    )
    return service, library_repo, library_db


def _mb_release_group() -> dict:
    return {
        "title": "Album",
        "first-release-date": "2024-01-01",
        "primary-type": "Album",
        "disambiguation": "",
        "artist-credit": [],
    }


@pytest.mark.asyncio
async def test_get_album_basic_info_in_library_from_local_files_not_ledger():
    # in_library follows non-deleted local files, not the library_albums ledger row.
    # Files present with no ledger row must still report in_library.
    service, library_repo, library_db = _make_service()
    service._get_cached_album_info = AsyncMock(return_value=None)
    service._fetch_release_group = AsyncMock(return_value=_mb_release_group())
    library_repo.get_requested_mbids = AsyncMock(return_value=set())
    library_repo.get_album_details = AsyncMock(return_value=None)
    library_db.has_album_files = AsyncMock(return_value=True)
    library_db.get_album_by_mbid = AsyncMock(return_value=None)

    result = await service.get_album_basic_info("8e1e9e51-38dc-4df3-8027-a0ada37d4674")

    assert result.in_library is True
    library_db.has_album_files.assert_awaited()
    library_db.get_album_by_mbid.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_album_basic_info_not_in_library_when_files_gone_despite_ledger_row():
    # Files soft-deleted but a stale ledger row lingers: in_library follows the files.
    service, library_repo, library_db = _make_service()
    service._get_cached_album_info = AsyncMock(return_value=None)
    service._fetch_release_group = AsyncMock(return_value=_mb_release_group())
    library_repo.get_requested_mbids = AsyncMock(return_value=set())
    library_repo.get_album_details = AsyncMock(return_value=None)
    library_db.has_album_files = AsyncMock(return_value=False)
    library_db.get_album_by_mbid = AsyncMock(return_value={"mbid": "stale"})

    result = await service.get_album_basic_info("8e1e9e51-38dc-4df3-8027-a0ada37d4674")

    assert result.in_library is False
