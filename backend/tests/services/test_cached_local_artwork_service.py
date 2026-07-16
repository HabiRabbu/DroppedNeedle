from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repositories.coverart_disk_cache import get_cache_filename
from services.home.cached_local_artwork_service import CachedLocalArtworkService


@pytest.mark.asyncio
async def test_provider_association_reads_only_existing_normal_cache_bytes(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "covers"
    cache_dir.mkdir()
    content = b"\xff\xd8\xfflocal-cover"
    path = cache_dir / f"{get_cache_filename('rg_provider-id', '500')}.bin"
    path.write_bytes(content)
    store = AsyncMock()
    store.get_cached_local_artwork_context.return_value = {
        "source": "provider",
        "source_locator": "provider-id",
        "provider_id": "provider-id",
        "version": 3,
    }
    service = CachedLocalArtworkService(store, cache_dir)

    result = await service.get("local-album-id", 3)

    assert result is not None
    assert result[:3] == (content, "image/jpeg", "provider")
    store.get_cached_local_artwork_context.assert_awaited_once_with("local-album-id", 3)


@pytest.mark.asyncio
async def test_missing_cache_claim_is_terminal_and_does_not_call_a_provider(
    tmp_path: Path,
) -> None:
    store = AsyncMock()
    store.get_cached_local_artwork_context.return_value = {
        "source": "provider",
        "source_locator": "missing",
        "provider_id": "missing",
        "version": 1,
    }
    service = CachedLocalArtworkService(store, tmp_path / "covers")

    assert await service.get("uuid-shaped-local-id", 1) is None
    assert not hasattr(service, "_provider")


@pytest.mark.asyncio
async def test_embedded_association_reads_tags_off_the_event_loop(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "album.flac"
    audio_path.write_bytes(b"audio")
    store = AsyncMock()
    store.get_cached_local_artwork_context.return_value = {
        "source": "embedded",
        "embedded_file_path": str(audio_path),
        "embedded_file_availability": "indexed",
        "version": 2,
    }
    service = CachedLocalArtworkService(store, tmp_path / "covers")
    service._tagger.read_cover_art = MagicMock(return_value=b"\x89PNG\r\n\x1a\ncover")

    result = await service.get("album", 2)

    assert result is not None
    assert result[1:3] == ("image/png", "embedded")
