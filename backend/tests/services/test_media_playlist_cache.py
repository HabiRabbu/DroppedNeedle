from unittest.mock import AsyncMock

import pytest

from services.media_playlist_cache import invalidate_media_playlist_cache


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "expected"),
    [
        (
            "jellyfin",
            [
                "jellyfin_playlists:user:user-a",
                "jellyfin_playlist:user:user-a",
                "jellyfin_playlist-meta:user:user-a",
            ],
        ),
        (
            "navidrome",
            [
                "navidrome:playlists:user:user-a",
                "navidrome:playlist:user:user-a",
                "navidrome:songs_browse:user:user-a",
            ],
        ),
        (
            "plex",
            [
                "plex:playlists:user:user-a",
                "plex:playlist:user:user-a",
            ],
        ),
    ],
)
async def test_invalidation_only_targets_the_users_source_prefixes(service, expected):
    cache = AsyncMock()
    cache.clear_prefix = AsyncMock(return_value=1)

    cleared = await invalidate_media_playlist_cache(cache, "user-a", service)

    assert [call.args[0] for call in cache.clear_prefix.await_args_list] == expected
    assert all("user-b" not in prefix for prefix in expected)
    assert cleared == len(expected)


@pytest.mark.asyncio
async def test_unknown_service_does_not_clear_cache():
    cache = AsyncMock()
    assert await invalidate_media_playlist_cache(cache, "user-a", "unknown") == 0
    cache.clear_prefix.assert_not_awaited()
