"""Integration tests - SettingsService invalidation methods clear the right cache keys."""

import pytest

from infrastructure.cache.cache_keys import (
    ALBUM_INFO_PREFIX,
    ARTIST_INFO_PREFIX,
    DISCOVER_RESPONSE_PREFIX,
    GENRE_ARTIST_PREFIX,
    HOME_RESPONSE_PREFIX,
    JELLYFIN_PREFIX,
    LB_PREFIX,
    LFM_PREFIX,
    LIBRARY_ARTIST_ALBUMS_PREFIX,
    LOCAL_FILES_PREFIX,
    SOURCE_RESOLUTION_PREFIX,
    musicbrainz_prefixes,
)
from infrastructure.cache.memory_cache import InMemoryCache
from services.settings_service import SettingsService


async def _build_service() -> tuple[SettingsService, InMemoryCache]:
    cache = InMemoryCache(max_entries=500)
    service = SettingsService(preferences_service=None, cache=cache)
    return service, cache


async def _populate(cache: InMemoryCache, keys: list[str]) -> None:
    for key in keys:
        await cache.set(key, "v", ttl_seconds=300)


@pytest.mark.asyncio(loop_scope="function")
async def test_clear_musicbrainz_cache():
    service, cache = await _build_service()

    mb_keys = [f"{p}dummy" for p in musicbrainz_prefixes()]
    extra_keys = [f"{ARTIST_INFO_PREFIX}art1", f"{ALBUM_INFO_PREFIX}alb1"]
    library_keys = [f"{LIBRARY_ARTIST_ALBUMS_PREFIX}mbid1", f"{LIBRARY_ARTIST_ALBUMS_PREFIX}mbid2"]
    unrelated = ["unrelated:key"]
    await _populate(cache, mb_keys + extra_keys + library_keys + unrelated)

    cleared = await service.clear_caches_for_preference_change()

    assert cleared == len(mb_keys) + len(extra_keys) + len(library_keys)
    for key in mb_keys + extra_keys + library_keys:
        assert await cache.get(key) is None
    assert await cache.get("unrelated:key") == "v"


@pytest.mark.asyncio(loop_scope="function")
async def test_clear_home_cache():
    service, cache = await _build_service()

    home_keys = [
        f"{HOME_RESPONSE_PREFIX}page1",
        f"{DISCOVER_RESPONSE_PREFIX}rock",
        f"{GENRE_ARTIST_PREFIX}pop",
        f"{JELLYFIN_PREFIX}lib",
        f"{LB_PREFIX}stats",
        f"{LFM_PREFIX}chart",
    ]
    unrelated = ["unrelated:key"]
    await _populate(cache, home_keys + unrelated)

    cleared = await service.clear_home_cache()

    assert cleared == len(home_keys)
    for key in home_keys:
        assert await cache.get(key) is None
    assert await cache.get("unrelated:key") == "v"


@pytest.mark.asyncio(loop_scope="function")
async def test_clear_source_resolution_cache():
    """SOURCE_RESOLUTION_PREFIX = 'source_resolution' (no trailing colon)
    must match both 'source_resolution:x' and 'source_resolution_tracks:y'."""
    service, cache = await _build_service()

    sr_keys = [
        f"{SOURCE_RESOLUTION_PREFIX}:track1",
        f"{SOURCE_RESOLUTION_PREFIX}_tracks:track2",
    ]
    unrelated = ["unrelated:key"]
    await _populate(cache, sr_keys + unrelated)

    cleared = await service.clear_source_resolution_cache()

    assert cleared == len(sr_keys)
    for key in sr_keys:
        assert await cache.get(key) is None
    assert await cache.get("unrelated:key") == "v"


@pytest.mark.asyncio(loop_scope="function")
async def test_clear_local_files_cache():
    service, cache = await _build_service()

    lf_keys = [f"{LOCAL_FILES_PREFIX}scan1", f"{LOCAL_FILES_PREFIX}scan2"]
    unrelated = ["unrelated:key"]
    await _populate(cache, lf_keys + unrelated)

    cleared = await service.clear_local_files_cache()

    assert cleared == len(lf_keys)
    for key in lf_keys:
        assert await cache.get(key) is None
    assert await cache.get("unrelated:key") == "v"


@pytest.mark.asyncio(loop_scope="function")
async def test_unrelated_keys_survive():
    """Clearing one domain must not affect keys from other domains."""
    service, cache = await _build_service()

    survivor_keys = [
        f"{LOCAL_FILES_PREFIX}scan",
        f"{SOURCE_RESOLUTION_PREFIX}:t1",
        f"{LIBRARY_ARTIST_ALBUMS_PREFIX}mbid1",
    ]
    target_keys = [f"{p}x" for p in musicbrainz_prefixes()]
    await _populate(cache, survivor_keys + target_keys)

    await service.clear_home_cache()

    for key in survivor_keys:
        assert await cache.get(key) == "v", f"Key {key!r} was incorrectly cleared"


@pytest.mark.asyncio(loop_scope="function")
async def test_jellyfin_settings_change_clears_user_import_service():
    """Phase 6: configuring Jellyfin must rebuild the import service singleton so a
    newly-configured server is enumerable without an app restart."""
    from unittest.mock import patch, MagicMock, AsyncMock

    service, _cache = await _build_service()
    mbid = MagicMock()
    mbid.clear_jellyfin_mbid_index = AsyncMock()
    import_fn = MagicMock()
    auth_fn = MagicMock()

    with (
        patch("core.dependencies.get_jellyfin_repository", MagicMock()),
        patch("core.dependencies.get_jellyfin_playback_service", MagicMock()),
        patch("core.dependencies.get_jellyfin_library_service", MagicMock()),
        patch("core.dependencies.get_home_service", MagicMock()),
        patch("core.dependencies.get_home_charts_service", MagicMock()),
        patch("core.dependencies.get_mbid_store", MagicMock(return_value=mbid)),
        patch("core.dependencies.auth_providers.get_user_import_service", import_fn),
        patch("core.dependencies.auth_providers.get_jellyfin_user_auth_service", auth_fn),
    ):
        await service.on_jellyfin_settings_changed()

    import_fn.cache_clear.assert_called_once()
    auth_fn.cache_clear.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_plex_settings_change_clears_user_import_service():
    """Phase 6: configuring Plex must rebuild the import service singleton too."""
    from unittest.mock import patch, MagicMock, AsyncMock

    service, _cache = await _build_service()
    mbid = MagicMock()
    mbid.clear_plex_mbid_indexes = AsyncMock()
    plex_repo = MagicMock()
    plex_repo.clear_cache = AsyncMock()
    import_fn = MagicMock()
    auth_fn = MagicMock()

    with (
        patch("core.dependencies.get_plex_repository", MagicMock(return_value=plex_repo)),
        patch("core.dependencies.get_plex_library_service", MagicMock()),
        patch("core.dependencies.get_plex_playback_service", MagicMock()),
        patch("core.dependencies.get_home_service", MagicMock()),
        patch("core.dependencies.get_home_charts_service", MagicMock()),
        patch("core.dependencies.get_mbid_store", MagicMock(return_value=mbid)),
        patch("core.dependencies.auth_providers.get_user_import_service", import_fn),
        patch("core.dependencies.auth_providers.get_plex_user_auth_service", auth_fn),
    ):
        await service.on_plex_settings_changed(enabled=False)

    import_fn.cache_clear.assert_called_once()
    auth_fn.cache_clear.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_youtube_settings_change_clears_home_cache():
    """on_youtube_settings_changed should reset singleton AND clear home caches."""
    from unittest.mock import patch, MagicMock

    service, cache = await _build_service()

    home_keys = [
        f"{HOME_RESPONSE_PREFIX}page1",
        f"{DISCOVER_RESPONSE_PREFIX}rock",
    ]
    await _populate(cache, home_keys)

    mock_repo_fn = MagicMock()
    with patch("core.dependencies.get_youtube_repo", mock_repo_fn):
        await service.on_youtube_settings_changed()

    mock_repo_fn.cache_clear.assert_called_once()
    for key in home_keys:
        assert await cache.get(key) is None
