"""Tests for MusicBrainzAlbumMixin.get_release_group - the protocol method that maps
a raw MusicBrainz release-group dict to an AlbumInfo (year/title/artist backfill)."""

from unittest.mock import AsyncMock

import pytest

from models.album import AlbumInfo
from repositories.musicbrainz_album import MusicBrainzAlbumMixin


class _Repo(MusicBrainzAlbumMixin):
    def __init__(self) -> None:
        self._cache = AsyncMock()  # unused: get_release_group_by_id is stubbed per-test


_RG = {
    "id": "rg-1",
    "title": "OK Computer",
    "first-release-date": "1997-05-21",
    "primary-type": "Album",
    "artist-credit": [{"name": "Radiohead", "artist": {"id": "art-1", "name": "Radiohead"}}],
}


@pytest.mark.asyncio
async def test_get_release_group_maps_dict_to_album_info():
    repo = _Repo()
    repo.get_release_group_by_id = AsyncMock(return_value=_RG)

    info = await repo.get_release_group("rg-1")

    assert isinstance(info, AlbumInfo)
    assert info.year == 1997
    assert info.title == "OK Computer"
    assert info.artist_name == "Radiohead"
    assert info.artist_id == "art-1"  # the MBID radio_service reads as artist_mbid
    assert info.musicbrainz_id == "rg-1"


@pytest.mark.asyncio
async def test_get_release_group_returns_none_when_missing():
    repo = _Repo()
    repo.get_release_group_by_id = AsyncMock(return_value=None)
    assert await repo.get_release_group("rg-x") is None


@pytest.mark.asyncio
async def test_get_release_group_tolerates_sparse_dict():
    """No date and no artist-credit must still map without raising (year falls to None)."""
    repo = _Repo()
    repo.get_release_group_by_id = AsyncMock(return_value={"id": "rg-2", "title": "Untitled"})

    info = await repo.get_release_group("rg-2")

    assert info.year is None
    assert info.artist_name == "Unknown Artist"
    assert info.artist_id == ""


@pytest.mark.asyncio
async def test_fetch_rg_negative_caches_404_but_not_transient(monkeypatch):
    """A definitive 404 (mb_api_get -> {}) is negative-cached briefly so a merged/garbage
    mbid isn't re-fetched every discover build; a transient error stays uncached to retry."""
    import repositories.musicbrainz_album as mod

    repo = _Repo()
    repo._cache = AsyncMock()

    monkeypatch.setattr(mod, "mb_api_get", AsyncMock(return_value={}))
    assert await repo._fetch_release_group_by_id("rg-404", ["artist-credits"], "ck-404") is None
    repo._cache.set.assert_awaited_once_with("ck-404", {}, ttl_seconds=600)

    repo._cache.set.reset_mock()
    monkeypatch.setattr(mod, "mb_api_get", AsyncMock(side_effect=RuntimeError("503")))
    assert await repo._fetch_release_group_by_id("rg-503", ["artist-credits"], "ck-503") is None
    repo._cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_release_to_rg_resolution_threads_priority(monkeypatch):
    """#78: the album-page release->RG fallback passes the caller's priority, while
    background callers keep the BACKGROUND_SYNC default (honest-priority house rule)."""
    from types import SimpleNamespace

    import repositories.musicbrainz_album as mod
    from infrastructure.queue.priority_queue import RequestPriority

    repo = _Repo()
    repo._cache = AsyncMock()
    repo._cache.get = AsyncMock(return_value=None)

    api = AsyncMock(return_value=SimpleNamespace(release_group={"id": "rg-9"}, media=[]))
    monkeypatch.setattr(mod, "mb_api_get", api)

    resolved = await repo.get_release_group_id_from_release(
        "rel-1", priority=RequestPriority.USER_INITIATED
    )
    assert resolved == "rg-9"
    assert api.await_args.kwargs["priority"] is RequestPriority.USER_INITIATED

    api.reset_mock()
    assert await repo.get_release_group_id_from_release("rel-2") == "rg-9"
    assert api.await_args.kwargs["priority"] is RequestPriority.BACKGROUND_SYNC
