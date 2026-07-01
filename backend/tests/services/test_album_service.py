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


_MBID = "8e1e9e51-38dc-4df3-8027-a0ada37d4674"


def _rg_with_ranked_release() -> dict:
    # find_primary_release picks the XW "worldwide" release regardless of size.
    return {
        "title": "Album",
        "first-release-date": "2024-01-01",
        "primary-type": "Album",
        "disambiguation": "",
        "artist-credit": [],
        "releases": [{"id": "deluxe-rel", "status": "Official", "country": "XW"}],
    }


def _release_with_tracks(n: int) -> dict:
    return {
        "id": "rel",
        "media": [
            {
                "position": 1,
                "tracks": [
                    {"position": i, "recording": {"title": f"T{i}", "id": f"rec{i}", "length": 200000}}
                    for i in range(1, n + 1)
                ],
            }
        ],
    }


def _release_by_owned_or_deluxe(owned_id: str, owned_n: int, deluxe_n: int):
    async def _get(release_id: str, includes=None) -> dict:
        return _release_with_tracks(owned_n if release_id == owned_id else deluxe_n)

    return _get


@pytest.mark.asyncio
async def test_get_album_info_uses_owned_release_edition_not_the_larger_ranked_release():
    # An owned album shows the edition on disc (12 tracks), not the deluxe ranked release (28).
    service, _library_repo, library_db = _make_service()
    service._get_cached_album_info = AsyncMock(return_value=None)
    service._fetch_release_group = AsyncMock(return_value=_rg_with_ranked_release())
    service._apply_audiodb_album_images = AsyncMock(side_effect=lambda info, *a, **k: info)
    service._save_album_to_cache = AsyncMock()
    library_db.has_album_files = AsyncMock(return_value=True)
    library_db.get_album_release_mbid = AsyncMock(return_value="owned-rel")
    service._mb_repo.get_release_by_id = _release_by_owned_or_deluxe("owned-rel", owned_n=12, deluxe_n=28)

    result = await service.get_album_info(_MBID)

    assert result.total_tracks == 12
    library_db.get_album_release_mbid.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_album_info_falls_back_to_ranked_release_when_not_owned():
    # No local files: keep the existing ranked-release behaviour, no owned lookup.
    service, _library_repo, library_db = _make_service()
    service._get_cached_album_info = AsyncMock(return_value=None)
    service._fetch_release_group = AsyncMock(return_value=_rg_with_ranked_release())
    service._apply_audiodb_album_images = AsyncMock(side_effect=lambda info, *a, **k: info)
    service._save_album_to_cache = AsyncMock()
    library_db.has_album_files = AsyncMock(return_value=False)
    service._check_in_library = AsyncMock(return_value=False)
    library_db.get_album_release_mbid = AsyncMock(return_value="owned-rel")
    service._mb_repo.get_release_by_id = _release_by_owned_or_deluxe("owned-rel", owned_n=12, deluxe_n=28)

    result = await service.get_album_info(_MBID)

    assert result.total_tracks == 28
    library_db.get_album_release_mbid.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_album_tracks_info_prefers_owned_release_edition():
    service, _library_repo, library_db = _make_service()
    service._get_cached_album_info = AsyncMock(return_value=None)
    service._fetch_release_group = AsyncMock(return_value=_rg_with_ranked_release())
    library_db.get_album_release_mbid = AsyncMock(return_value="owned-rel")
    service._mb_repo.get_release_by_id = _release_by_owned_or_deluxe("owned-rel", owned_n=12, deluxe_n=28)

    result = await service.get_album_tracks_info(_MBID)

    assert result.total_tracks == 12
    assert len(result.tracks) == 12
