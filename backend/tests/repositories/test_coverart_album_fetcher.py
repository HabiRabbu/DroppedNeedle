from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.queue.priority_queue import RequestPriority
from repositories.coverart_album import AlbumCoverFetcher


@pytest.mark.asyncio
async def test_release_local_sources_prefers_library_before_jellyfin():
    mb_repo = MagicMock()
    mb_repo.get_release_group_id_from_release = AsyncMock(return_value='rg-id')

    fetcher = AlbumCoverFetcher(
        http_get_fn=AsyncMock(),
        write_cache_fn=AsyncMock(),
        library_repo=MagicMock(),
        mb_repo=mb_repo,
        jellyfin_repo=MagicMock(),
    )

    fetcher._fetch_from_library = AsyncMock(return_value=(b'img', 'image/jpeg', 'library'))
    fetcher._fetch_from_jellyfin = AsyncMock(return_value=(b'img2', 'image/jpeg', 'jellyfin'))

    result = await fetcher._fetch_release_local_sources(
        'release-id',
        Path('/tmp/cover.bin'),
        '500',
    )

    assert result is not None
    assert result[2] == 'library'
    fetcher._fetch_from_library.assert_awaited_once_with('rg-id', Path('/tmp/cover.bin'), size=500, priority=RequestPriority.IMAGE_FETCH)
    fetcher._fetch_from_jellyfin.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_local_sources_uses_jellyfin_when_library_misses():
    mb_repo = MagicMock()
    mb_repo.get_release_group_id_from_release = AsyncMock(return_value='rg-id')

    fetcher = AlbumCoverFetcher(
        http_get_fn=AsyncMock(),
        write_cache_fn=AsyncMock(),
        library_repo=MagicMock(),
        mb_repo=mb_repo,
        jellyfin_repo=MagicMock(),
    )

    fetcher._fetch_from_library = AsyncMock(return_value=None)
    fetcher._fetch_from_jellyfin = AsyncMock(return_value=(b'img2', 'image/jpeg', 'jellyfin'))

    result = await fetcher._fetch_release_local_sources(
        'release-id',
        Path('/tmp/cover.bin'),
        '500',
    )

    assert result is not None
    assert result[2] == 'jellyfin'
    fetcher._fetch_from_library.assert_awaited_once_with('rg-id', Path('/tmp/cover.bin'), size=500, priority=RequestPriority.IMAGE_FETCH)
    fetcher._fetch_from_jellyfin.assert_awaited_once_with('rg-id', Path('/tmp/cover.bin'), priority=RequestPriority.IMAGE_FETCH)
