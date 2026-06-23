"""Tests for LibraryService._resolve_album_tracks and resolve_tracks_batch."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.v1.schemas.library import TrackResolveRequest, TrackResolveResponse, ResolvedTrack
from services.library_service import LibraryService


def _item(mbid: str, disc: int = 1, track: int = 1):
    """Shorthand to build a TrackResolveRequest.Item-like object."""
    from api.v1.schemas.library import TrackResolveItem
    return TrackResolveItem(release_group_mbid=mbid, disc_number=disc, track_number=track)


def _make_service(
    *,
    local_service=None,
    jf_service=None,
    nd_service=None,
    preferences=None,
    cache=None,
):
    library_repo = MagicMock()
    library_db = MagicMock()
    memory_cache = cache or MagicMock()
    disk_cache = MagicMock()
    prefs = preferences or MagicMock()
    audiodb_image_service = MagicMock()
    cover_repo = MagicMock()

    service = LibraryService(
        library_repo=library_repo,
        library_db=library_db,
        cover_repo=cover_repo,
        preferences_service=prefs,
        memory_cache=memory_cache,
        disk_cache=disk_cache,
        audiodb_image_service=audiodb_image_service,
        local_files_service=local_service,
        jellyfin_library_service=jf_service,
        navidrome_library_service=nd_service,
    )
    return service


@pytest.mark.asyncio
async def test_resolve_tracks_batch_empty_items():
    service = _make_service()
    result = await service.resolve_tracks_batch([])
    assert isinstance(result, TrackResolveResponse)
    assert result.items == []


@pytest.mark.asyncio
async def test_resolve_tracks_batch_respects_max_items():
    service = _make_service()
    items = [_item(f"mbid-{i}", track=i) for i in range(60)]

    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    service._memory_cache = cache

    local_service = MagicMock()
    local_match = MagicMock()
    local_match.found = False
    local_match.tracks = []
    local_service.match_album_by_mbid = AsyncMock(return_value=local_match)
    service._local_files_service = local_service

    prefs = MagicMock()
    prefs.get_navidrome_connection_raw = MagicMock(side_effect=Exception("unconfigured"))
    prefs.get_jellyfin_connection = MagicMock(side_effect=Exception("unconfigured"))
    service._preferences_service = prefs

    result = await service.resolve_tracks_batch(items)
    assert len(result.items) <= 50


@pytest.mark.asyncio
async def test_resolve_tracks_batch_missing_mbid_returns_base():
    service = _make_service()
    items = [_item("", disc=1, track=1)]

    result = await service.resolve_tracks_batch(items)
    assert len(result.items) == 1
    assert result.items[0].source is None
    assert result.items[0].stream_url is None


@pytest.mark.asyncio
async def test_resolve_tracks_batch_uses_cache_hit():
    cache = MagicMock()
    cached_map = {"1:1": ("local", "file-123", "flac", 240.0)}
    cache.get = AsyncMock(return_value=cached_map)
    cache.set = AsyncMock()

    service = _make_service(cache=cache)
    items = [_item("mbid-abc", disc=1, track=1)]

    result = await service.resolve_tracks_batch(items)
    assert len(result.items) == 1
    assert result.items[0].source == "local"
    assert result.items[0].stream_url == "/api/v1/stream/local/file-123"
    assert result.items[0].format == "flac"
    assert result.items[0].duration == 240.0
