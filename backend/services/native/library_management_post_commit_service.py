"""Post-commit cache consistency and durable media-server notification enqueueing."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable

import msgspec

from infrastructure.cache.cache_keys import library_identification_prefixes
from infrastructure.cache.disk_cache import DiskMetadataCache
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.persistence import DiscoverySnapshotStore
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_management import (
    EXTERNAL_REFRESH_NOT_CONFIGURED,
    EXTERNAL_REFRESH_PROTOCOL_UNAVAILABLE,
    LibraryManagementExternalRefreshDelivery,
)
from models.library_management_planning import PinnedLibraryManagementProfile
from repositories.protocols import JellyfinRepositoryProtocol
from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)

_DELIVERY_NAMESPACE = uuid.UUID("cb89c70c-f51d-46eb-90d1-d7efe3410647")


class LibraryManagementPostCommitService:
    def __init__(
        self,
        store: NativeLibraryStore,
        preferences: PreferencesService,
        memory_cache: CacheInterface,
        disk_cache: DiskMetadataCache,
        discovery_snapshots: DiscoverySnapshotStore,
        jellyfin_getter: Callable[[], JellyfinRepositoryProtocol],
    ) -> None:
        self._store = store
        self._preferences = preferences
        self._memory_cache = memory_cache
        self._disk_cache = disk_cache
        self._discovery_snapshots = discovery_snapshots
        self._jellyfin_getter = jellyfin_getter

    async def after_commit(
        self, local_track_ids: set[str], local_album_ids: set[str]
    ) -> None:
        tracks = await self._store.get_target_tracks_by_ids(sorted(local_track_ids))
        await self._invalidate_native_caches(tracks)

        states = await asyncio.gather(
            *(
                self._store.get_track_management_state(track_id)
                for track_id in sorted(local_track_ids)
            )
        )
        operation_ids = {
            state.last_operation_job_id
            for state in states
            if state is not None and state.last_operation_job_id
        }
        for operation_id in sorted(operation_ids):
            await self._enqueue_external_refreshes(operation_id)

    async def _invalidate_native_caches(self, tracks: dict[str, dict]) -> None:
        from services.search_service import SearchService

        SearchService.clear_cached_results()
        results = await asyncio.gather(
            *(
                self._memory_cache.clear_prefix(prefix)
                for prefix in library_identification_prefixes()
            ),
            self._discovery_snapshots.mark_discover_stale(),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Library Management cache invalidation failed")

        release_group_mbids = {
            str(track["provider_release_group_mbid"])
            for track in tracks.values()
            if track.get("provider_release_group_mbid")
        }
        artist_mbids = {
            str(value)
            for track in tracks.values()
            for value in (
                track.get("provider_album_artist_mbid"),
                track.get("provider_artist_mbid"),
            )
            if value
        }
        disk_results = await asyncio.gather(
            *(self._disk_cache.delete_album(value) for value in release_group_mbids),
            *(self._disk_cache.delete_artist(value) for value in artist_mbids),
            return_exceptions=True,
        )
        for result in disk_results:
            if isinstance(result, Exception):
                logger.warning("Library Management disk cache invalidation failed")

    async def _enqueue_external_refreshes(self, operation_id: str) -> None:
        snapshot = await self._store.get_library_management_job_snapshot(operation_id)
        if snapshot is None:
            return
        pinned = msgspec.json.decode(
            snapshot.profile_snapshot_json,
            type=PinnedLibraryManagementProfile,
        )
        if not pinned.profile.notification.refresh_external_servers:
            return

        settings = self._preferences.get_library_management_settings_raw()
        external = settings.external_refresh
        if not external.enabled:
            return

        now = time.time()
        max_attempts = external.retry_attempts + 1
        enabled_targets = (
            ("jellyfin", external.jellyfin_enabled),
            ("plex", external.plex_enabled),
            ("navidrome", external.navidrome_enabled),
        )
        for target, enabled in enabled_targets:
            if not enabled:
                continue
            failure_code = None
            state = "pending"
            if target == "jellyfin":
                if not self._jellyfin_getter().is_configured():
                    state = "unavailable"
                    failure_code = EXTERNAL_REFRESH_NOT_CONFIGURED
            else:
                state = "unavailable"
                failure_code = EXTERNAL_REFRESH_PROTOCOL_UNAVAILABLE
            await self._store.ensure_library_management_external_refresh(
                LibraryManagementExternalRefreshDelivery(
                    id=str(uuid.uuid5(_DELIVERY_NAMESPACE, f"{operation_id}:{target}")),
                    operation_job_id=operation_id,
                    target=target,
                    state=state,
                    max_attempts=max_attempts,
                    retry_delay_seconds=external.retry_delay_seconds,
                    not_before=now,
                    failure_code=failure_code,
                    created_at=now,
                    updated_at=now,
                    completed_at=now if state == "unavailable" else None,
                )
            )
