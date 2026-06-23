"""Service-level tests for filter-aware artist release pagination."""
import os
import tempfile

os.environ.setdefault("ROOT_APP_DIR", tempfile.mkdtemp())

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.artist_service import ArtistService


ARTIST_MBID = "f4a31f0a-51dd-4fa7-986d-3095c40c5ed9"


def _make_release_group(rg_id: str, title: str, primary_type: str, date: str = "2020-01-01") -> dict:
    return {
        "id": rg_id,
        "title": title,
        "primary-type": primary_type,
        "secondary-types": [],
        "first-release-date": date,
    }


def _make_prefs(primary_types: list[str] | None = None, secondary_types: list[str] | None = None) -> MagicMock:
    p = MagicMock()
    p.get_preferences.return_value = MagicMock(
        primary_types=primary_types if primary_types is not None else ["Album", "Single", "EP"],
        secondary_types=secondary_types if secondary_types is not None else ["Studio", "Live", "Compilation"],
    )
    p.get_advanced_settings.return_value = MagicMock(
        cache_ttl_artist_library=21600,
        cache_ttl_artist_non_library=3600,
    )
    return p


def _make_service(
    *,
    mb_release_pages: list[tuple[list[dict], int]] | None = None,
    prefs: MagicMock | None = None,
) -> ArtistService:
    mb_repo = AsyncMock()
    if mb_release_pages is not None:
        mb_repo.get_artist_release_groups = AsyncMock(side_effect=mb_release_pages)
    else:
        mb_repo.get_artist_release_groups = AsyncMock(return_value=([], 0))

    library_repo = MagicMock()
    library_repo.is_configured.return_value = False
    library_repo.get_library_mbids = AsyncMock(return_value=set())
    library_repo.get_requested_mbids = AsyncMock(return_value=set())
    library_repo.get_artist_mbids = AsyncMock(return_value=set())

    wikidata_repo = AsyncMock()

    memory_cache = AsyncMock()
    memory_cache.get = AsyncMock(return_value=None)
    memory_cache.set = AsyncMock()

    disk_cache = AsyncMock()
    disk_cache.get_artist = AsyncMock(return_value=None)
    disk_cache.set_artist = AsyncMock()

    return ArtistService(
        mb_repo=mb_repo,
        library_repo=library_repo,
        wikidata_repo=wikidata_repo,
        preferences_service=prefs or _make_prefs(),
        memory_cache=memory_cache,
        disk_cache=disk_cache,
    )


class TestFilterAwarePagination:
    @pytest.mark.asyncio
    async def test_single_page_fits_filter(self):
        rg1 = _make_release_group("rg-1", "Album A", "Album")
        rg2 = _make_release_group("rg-2", "Single B", "Single")
        svc = _make_service(mb_release_pages=[([rg1, rg2], 2)])

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert len(result.albums) == 1
        assert result.albums[0].title == "Album A"
        assert len(result.singles) == 1
        assert result.singles[0].title == "Single B"
        assert result.has_more is False
        assert result.next_offset is None
        assert result.returned_count == 2
        assert result.source_total_count == 2

    @pytest.mark.asyncio
    async def test_sparse_filter_scans_multiple_batches(self):
        batch1 = [_make_release_group(f"rg-{i}", f"Broadcast {i}", "Broadcast") for i in range(5)]
        batch2 = [_make_release_group("rg-album", "Real Album", "Album")]
        svc = _make_service(
            mb_release_pages=[
                (batch1, 6),
                (batch2, 6),
            ]
        )

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.albums[0].title == "Real Album"
        assert result.returned_count == 1
        assert result.source_total_count == 6

    @pytest.mark.asyncio
    async def test_has_more_true_when_unscanned_raw_data_remains(self):
        rgs = [_make_release_group("rg-1", "Album 1", "Album")]
        svc = _make_service(mb_release_pages=[(rgs, 200), ([], 200), ([], 200)])

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.has_more is True
        assert result.next_offset is not None
        assert result.returned_count == 1

    @pytest.mark.asyncio
    async def test_next_offset_is_scan_position(self):
        batch1 = [_make_release_group(f"rg-{i}", f"Album {i}", "Album") for i in range(100)]
        svc = _make_service(mb_release_pages=[(batch1, 200)])

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=10)

        assert result.has_more is True
        assert result.next_offset == 100

    @pytest.mark.asyncio
    async def test_no_duplicates_within_scan(self):
        batch1 = [_make_release_group(f"rg-{i}", f"Album {i}", "Album") for i in range(5)]
        batch2 = [_make_release_group(f"rg-{i}", f"Album {i}", "Album") for i in range(3, 8)]
        svc = _make_service(
            mb_release_pages=[
                (batch1, 8),
                (batch2, 8),
            ]
        )

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        all_ids = [r.id for r in result.albums]
        assert len(all_ids) == len(set(all_ids))

    @pytest.mark.asyncio
    async def test_no_drops_across_sequential_pages(self):
        rgs = [_make_release_group(f"rg-{i}", f"Album {i}", "Album") for i in range(10)]
        svc = _make_service(mb_release_pages=[(rgs, 10)])

        page1 = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=3)
        assert page1.returned_count == 10
        assert page1.has_more is False
        assert page1.next_offset is None

    @pytest.mark.asyncio
    async def test_empty_result_set(self):
        svc = _make_service(mb_release_pages=[([], 0)])

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.returned_count == 0
        assert result.has_more is False
        assert result.next_offset is None
        assert result.source_total_count == 0

    @pytest.mark.asyncio
    async def test_offset_reflects_client_param(self):
        rg = _make_release_group("rg-1", "Album 1", "Album")
        svc = _make_service(mb_release_pages=[([rg], 1)])

        result = await svc.get_artist_releases(ARTIST_MBID, offset=200, limit=50)

        assert result.offset == 200

    @pytest.mark.asyncio
    async def test_returned_count_across_categories(self):
        rgs = [
            _make_release_group("rg-a1", "Album 1", "Album"),
            _make_release_group("rg-a2", "Album 2", "Album"),
            _make_release_group("rg-s1", "Single 1", "Single"),
            _make_release_group("rg-e1", "EP 1", "EP"),
        ]
        svc = _make_service(mb_release_pages=[(rgs, 4)])

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.returned_count == 4
        assert len(result.albums) == 2
        assert len(result.singles) == 1
        assert len(result.eps) == 1

    @pytest.mark.asyncio
    async def test_limit_controls_scan_termination_all_items_returned(self):
        rgs = [
            _make_release_group("rg-a1", "Album 1", "Album"),
            _make_release_group("rg-a2", "Album 2", "Album"),
            _make_release_group("rg-a3", "Album 3", "Album"),
            _make_release_group("rg-s1", "Single 1", "Single"),
            _make_release_group("rg-e1", "EP 1", "EP"),
        ]
        svc = _make_service(mb_release_pages=[(rgs, 5)])

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=3)

        assert result.returned_count == 5
        assert len(result.albums) == 3
        assert len(result.singles) == 1
        assert len(result.eps) == 1
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_exception_returns_empty_page(self):
        svc = _make_service()
        svc._library_repo.get_library_mbids = AsyncMock(side_effect=RuntimeError("boom"))

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.returned_count == 0
        assert result.has_more is False
        assert result.next_offset is None

    @pytest.mark.asyncio
    async def test_empty_filter_types_returns_immediately(self):
        svc = _make_service(
            prefs=_make_prefs(primary_types=[], secondary_types=[]),
        )

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.returned_count == 0
        assert result.has_more is False
        assert result.next_offset is None
        svc._mb_repo.get_artist_release_groups.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_types_filtered_out_except_one(self):
        batch = (
            [_make_release_group(f"rg-b{i}", f"Broadcast {i}", "Broadcast") for i in range(5)]
            + [_make_release_group("rg-album", "Found Album", "Album")]
        )
        svc = _make_service(
            mb_release_pages=[
                (batch, 6),
            ]
        )

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.returned_count == 1
        assert result.albums[0].title == "Found Album"
        assert result.source_total_count == 6
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_global_sort_across_batches(self):
        batch1 = [_make_release_group("rg-a", "Old Album", "Album", "2010-01-01")]
        batch2 = [_make_release_group("rg-b", "New Album", "Album", "2020-01-01")]
        svc = _make_service(
            mb_release_pages=[
                (batch1, 2),
                (batch2, 2),
            ]
        )

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert len(result.albums) == 2
        assert result.albums[0].title == "New Album"
        assert result.albums[1].title == "Old Album"

    @pytest.mark.asyncio
    async def test_scan_batch_cap_stops_early(self):
        batches = [([_make_release_group(f"rg-{i}", f"Album {i}", "Album")], 5000) for i in range(25)]
        svc = _make_service(mb_release_pages=batches)

        result = await svc.get_artist_releases(ARTIST_MBID, offset=0, limit=50)

        assert result.has_more is True
        assert result.next_offset is not None
        assert result.next_offset == 2
