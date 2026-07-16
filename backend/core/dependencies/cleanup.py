"""Application lifecycle and targeted cache invalidation."""

from __future__ import annotations

import asyncio
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
    get_target_album_discovery_service,
    get_target_artist_discovery_service,
    get_target_discover_queue_manager,
    get_target_discover_service,
    get_target_home_charts_service,
    get_target_home_service,
    get_target_wrapped_service,
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


def clear_library_policy_dependent_caches() -> None:
    from .service_providers import (
        get_library_policy_resolver,
        get_target_download_orchestrator,
        get_target_download_service,
        get_target_file_processor,
        get_target_import_library_service,
    )

    for provider in (
        get_library_policy_resolver,
        get_target_import_library_service,
        get_target_file_processor,
        get_target_download_orchestrator,
        get_target_download_service,
    ):
        provider.cache_clear()


def clear_lastfm_dependent_caches() -> None:
    """Clear LRU caches for all services that hold a reference to LastFmRepository."""
    get_artist_discovery_service.cache_clear()
    get_target_artist_discovery_service.cache_clear()
    get_album_discovery_service.cache_clear()
    get_target_album_discovery_service.cache_clear()
    get_artist_enrichment_service.cache_clear()
    get_album_enrichment_service.cache_clear()
    get_search_enrichment_service.cache_clear()
    get_scrobble_service.cache_clear()
    get_home_charts_service.cache_clear()
    get_target_home_charts_service.cache_clear()
    get_home_service.cache_clear()
    get_target_home_service.cache_clear()
    get_discover_service.cache_clear()
    get_target_discover_service.cache_clear()
    get_discover_queue_manager.cache_clear()
    get_target_discover_queue_manager.cache_clear()
    get_lastfm_auth_service.cache_clear()
    get_target_wrapped_service.cache_clear()


def clear_listenbrainz_dependent_caches() -> None:
    """Clear LRU caches for all services that hold a reference to ListenBrainzRepository."""
    get_listenbrainz_repository.cache_clear()
    get_artist_discovery_service.cache_clear()
    get_target_artist_discovery_service.cache_clear()
    get_album_discovery_service.cache_clear()
    get_target_album_discovery_service.cache_clear()
    get_search_enrichment_service.cache_clear()
    get_scrobble_service.cache_clear()
    get_home_charts_service.cache_clear()
    get_target_home_charts_service.cache_clear()
    get_home_service.cache_clear()
    get_target_home_service.cache_clear()
    get_discover_service.cache_clear()
    get_target_discover_service.cache_clear()
    get_discover_queue_manager.cache_clear()
    get_target_discover_queue_manager.cache_clear()
    get_target_wrapped_service.cache_clear()


async def init_app_state(app) -> None:
    settings = get_settings()
    await asyncio.to_thread(init_crypto, settings.root_app_dir / "config")


async def cleanup_app_state(
    *, queue_manager_getter=None, genre_prewarm_getter=None
) -> None:
    queue_manager_getter = queue_manager_getter or get_discover_queue_manager
    genre_prewarm_getter = genre_prewarm_getter or get_genre_cover_prewarm_service
    try:
        queue_mgr = queue_manager_getter()
        queue_mgr.invalidate()
    except (AttributeError, RuntimeError) as exc:
        logger.error(
            "Failed to invalidate discover queue manager during cleanup: %s", exc
        )

    await close_http_clients()

    try:
        prewarm_svc = genre_prewarm_getter()
        await prewarm_svc.shutdown()
    except (AttributeError, RuntimeError, OSError) as exc:
        logger.error(
            "Failed to shut down genre prewarm service during cleanup: %s", exc
        )

    clear_all_singletons()
