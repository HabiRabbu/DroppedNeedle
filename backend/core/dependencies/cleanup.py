"""Application lifecycle and targeted cache invalidation."""

from __future__ import annotations

import logging

from core.config import get_settings
from infrastructure.crypto import init_crypto
from infrastructure.http.client import close_http_clients

from ._registry import clear_all_singletons
from .service_providers import (
    get_artist_discovery_service,
    get_artist_enrichment_service,
    get_album_enrichment_service,
    get_album_discovery_service,
    get_search_enrichment_service,
    get_scrobble_service,
    get_home_charts_service,
    get_home_service,
    get_discover_service,
    get_discover_queue_manager,
    get_lastfm_auth_service,
    get_genre_cover_prewarm_service,
)
from .repo_providers import get_listenbrainz_repository

logger = logging.getLogger(__name__)


def clear_lastfm_dependent_caches() -> None:
    """Clear LRU caches for all services that hold a reference to LastFmRepository."""
    get_artist_discovery_service.cache_clear()
    get_artist_enrichment_service.cache_clear()
    get_album_enrichment_service.cache_clear()
    get_search_enrichment_service.cache_clear()
    get_scrobble_service.cache_clear()
    get_home_charts_service.cache_clear()
    get_home_service.cache_clear()
    get_discover_service.cache_clear()
    get_discover_queue_manager.cache_clear()
    get_lastfm_auth_service.cache_clear()


def clear_listenbrainz_dependent_caches() -> None:
    """Clear LRU caches for all services that hold a reference to ListenBrainzRepository."""
    get_listenbrainz_repository.cache_clear()
    get_artist_discovery_service.cache_clear()
    get_album_discovery_service.cache_clear()
    get_search_enrichment_service.cache_clear()
    get_scrobble_service.cache_clear()
    get_home_charts_service.cache_clear()
    get_home_service.cache_clear()
    get_discover_service.cache_clear()
    get_discover_queue_manager.cache_clear()


async def init_app_state(app) -> None:
    settings = get_settings()
    init_crypto(settings.root_app_dir / "config")


async def cleanup_app_state() -> None:
    # Graceful service shutdown
    try:
        queue_mgr = get_discover_queue_manager()
        queue_mgr.invalidate()
    except (AttributeError, RuntimeError) as exc:
        logger.error("Failed to invalidate discover queue manager during cleanup: %s", exc)

    await close_http_clients()

    # Shutdown genre prewarm service before clearing singletons
    try:
        prewarm_svc = get_genre_cover_prewarm_service()
        await prewarm_svc.shutdown()
    except (AttributeError, RuntimeError, OSError) as exc:
        logger.error("Failed to shut down genre prewarm service during cleanup: %s", exc)

    # Automatic cleanup via registry; no manual list needed.
    clear_all_singletons()
