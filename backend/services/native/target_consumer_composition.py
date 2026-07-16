"""Isolated target consumer graph used by scratch and the offline replacement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.compat.bookmark_service import CompatBookmarkService
from services.compat.compat_scrobble_adapter import CompatScrobbleAdapter
from services.compat.discover_service import CompatDiscoverService
from services.compat.favorites_service import FavoritesService
from services.compat.id_map_service import CompatIdMapService
from services.compat.playback_report_service import PlaybackReportService
from services.compat.play_queue_service import CompatPlayQueueService
from services.compat.target_cover_art_service import TargetCoverArtService
from services.compat.target_library_view_service import TargetLibraryViewService
from services.home.cached_local_artwork_service import CachedLocalArtworkService
from services.local_files_service import LocalFilesService
from services.native.library_ownership_service import LibraryOwnershipService
from services.native.target_library_repository import TargetLibraryRepository
from services.native.target_native_library_service import TargetNativeLibraryService
from services.native.target_catalog_writer_service import TargetCatalogWriterService
from services.native.target_reference_adapters import (
    TargetDiscoveryBatchLibraryService,
    TargetBookmarkStore,
    TargetCompatIdMapStore,
    TargetFavoritesStore,
    TargetPlayHistoryStore,
    TargetPlayQueueStore,
    TargetPlaylistRepository,
)
from services.playlist_service import PlaylistService
from services.scrobble_service import ScrobbleService


@dataclass(frozen=True)
class TargetConsumerComposition:
    repository: TargetLibraryRepository
    ownership: LibraryOwnershipService
    native_library: TargetNativeLibraryService
    catalog_writer: TargetCatalogWriterService
    favorites: FavoritesService
    history: TargetPlayHistoryStore
    view: TargetLibraryViewService
    playlists: PlaylistService
    playlist_repository: TargetPlaylistRepository
    discovery_batch_library: TargetDiscoveryBatchLibraryService
    id_map: CompatIdMapService
    bookmarks: CompatBookmarkService
    play_queue: CompatPlayQueueService
    scrobble: CompatScrobbleAdapter
    playback_report: PlaybackReportService
    covers: TargetCoverArtService
    local_files: LocalFilesService
    discover: CompatDiscoverService


def build_target_consumer_composition(
    *,
    store: NativeLibraryStore,
    preferences: Any,
    auth_store: Any,
    provider_covers: Any,
    cache: Any,
    cache_dir: Path,
    client_factory: Any,
    listening_prefs_store: Any,
    now_playing: Any,
    request_history: Any | None = None,
) -> TargetConsumerComposition:
    repository = TargetLibraryRepository(store, request_history)
    favorites = FavoritesService(TargetFavoritesStore(store))
    history = TargetPlayHistoryStore(store)
    view = TargetLibraryViewService(store, favorites, history)
    local_files = LocalFilesService(repository, preferences, cache)
    native_library = TargetNativeLibraryService(store)
    scrobble = CompatScrobbleAdapter(
        ScrobbleService(client_factory, listening_prefs_store, history),
        view,
        now_playing,
    )
    playlist_repository = TargetPlaylistRepository(store)

    def recycle_bin() -> Path | None:
        from services.native.recycle_bin import resolve_bin_path

        roots = preferences.get_typed_library_settings().library_roots
        return resolve_bin_path(
            preferences.get_download_policy().recycle_bin_path,
            [root.path for root in roots],
        )

    catalog_writer = TargetCatalogWriterService(
        store,
        local_files,
        native_library,
        recycle_bin_getter=recycle_bin,
    )
    return TargetConsumerComposition(
        repository=repository,
        ownership=LibraryOwnershipService(store),
        native_library=native_library,
        catalog_writer=catalog_writer,
        favorites=favorites,
        history=history,
        view=view,
        playlists=PlaylistService(
            None,
            cache_dir,
            auth_store=auth_store,
            library_db=repository,
            async_repo=playlist_repository,
        ),
        playlist_repository=playlist_repository,
        discovery_batch_library=TargetDiscoveryBatchLibraryService(catalog_writer),
        id_map=CompatIdMapService(TargetCompatIdMapStore(store)),
        bookmarks=CompatBookmarkService(TargetBookmarkStore(store)),
        play_queue=CompatPlayQueueService(TargetPlayQueueStore(store)),
        scrobble=scrobble,
        playback_report=PlaybackReportService(scrobble, view),
        covers=TargetCoverArtService(
            store,
            provider_covers,
            CachedLocalArtworkService(store, cache_dir / "covers"),
        ),
        local_files=local_files,
        discover=CompatDiscoverService(
            library_db=repository,
            library_view_service=view,
            preferences_service=preferences,
            play_history_store=history,
        ),
    )
