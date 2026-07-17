from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.cache.cache_keys import (
    JELLYFIN_PREFIX,
    NAVIDROME_PREFIX,
    PLEX_PREFIX,
)


async def invalidate_media_playlist_cache(
    cache: CacheInterface, user_id: str, service: str
) -> int:
    scope = f"user:{user_id}"
    prefixes = {
        "jellyfin": (
            f"{JELLYFIN_PREFIX}playlists:{scope}",
            f"{JELLYFIN_PREFIX}playlist:{scope}",
            f"{JELLYFIN_PREFIX}playlist-meta:{scope}",
        ),
        "navidrome": (
            f"{NAVIDROME_PREFIX}playlists:{scope}",
            f"{NAVIDROME_PREFIX}playlist:{scope}",
            f"{NAVIDROME_PREFIX}songs_browse:{scope}",
        ),
        "plex": (
            f"{PLEX_PREFIX}playlists:{scope}",
            f"{PLEX_PREFIX}playlist:{scope}",
        ),
    }.get(service, ())
    cleared = 0
    for prefix in prefixes:
        cleared += await cache.clear_prefix(prefix)
    return cleared
