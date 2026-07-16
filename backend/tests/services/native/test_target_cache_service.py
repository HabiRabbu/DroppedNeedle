import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.cache.cache_keys import library_identification_prefixes
from infrastructure.cache.memory_cache import InMemoryCache
from infrastructure.persistence.library_db import LibraryDB
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.local_catalog import CatalogMembership, LocalAlbum, LocalArtist, LocalTrack
from services.native.target_cache_service import TargetCacheService
from services.native.target_library_repository import TargetLibraryRepository
from services.search_service import SearchService


def _membership(root: Path) -> CatalogMembership:
    track_path = root / "target.flac"
    track_path.write_bytes(b"target-audio")
    artist = LocalArtist(
        id="target-artist",
        display_name="Target Artist",
        folded_name="target artist",
        kind="person",
        created_at=1,
        updated_at=1,
    )
    album = LocalAlbum(
        id="target-album",
        root_id="root-1",
        grouping_key="target-group",
        title="Target Album",
        album_artist_id=artist.id,
        album_artist_name=artist.display_name,
        created_at=1,
        updated_at=1,
    )
    track = LocalTrack(
        id="target-track",
        local_album_id=album.id,
        root_id="root-1",
        file_path=str(track_path),
        relative_path=track_path.name,
        path_hash="target-path",
        file_size_bytes=track_path.stat().st_size,
        file_mtime_ns=track_path.stat().st_mtime_ns,
        stat_revision="target-stat",
        title="Target Track",
        artist_name=artist.display_name,
        album_title=album.title,
        album_artist_name=artist.display_name,
        file_format="flac",
        imported_at=1,
    )
    return CatalogMembership(album=album, artists=[artist], tracks=[track])


@pytest.mark.asyncio
async def test_target_cache_stats_and_clear_preserve_both_catalogs(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "library.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
    lock = threading.Lock()
    LibraryDB(db_path, lock)
    store = NativeLibraryStore(db_path, lock)
    root = tmp_path / "Music"
    root.mkdir()
    await store.create_catalog_membership(_membership(root))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO library_artists "
            "(mbid_lower, mbid, name, album_count, raw_json) "
            "VALUES ('legacy-artist', 'legacy-artist', 'Legacy Artist', 7, '{}')"
        )
        connection.execute(
            "INSERT INTO library_albums "
            "(mbid_lower, mbid, title, raw_json) "
            "VALUES ('legacy-album', 'legacy-album', 'Legacy Album', '{}')"
        )

    cache = InMemoryCache()
    target_key = f"{library_identification_prefixes()[0]}proof"
    await cache.set(target_key, "target")
    await cache.set("unrelated:proof", "keep")
    disk_cache = SimpleNamespace(
        get_stats=lambda: {
            "total_count": 0,
            "album_count": 0,
            "artist_count": 0,
        }
    )
    service = TargetCacheService(cache, TargetLibraryRepository(store), disk_cache)

    stats = await service.get_stats()
    result = await service.clear_library_cache()

    assert stats.library_db_artist_count == 1
    assert stats.library_db_album_count == 1
    assert result.success is True
    assert result.cleared_memory_entries == 1
    assert await cache.get(target_key) is None
    assert await cache.get("unrelated:proof") == "keep"
    assert (await store.get_target_library_stats())["total_albums"] == 1
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM library_albums").fetchone() == (
            1,
        )
        assert connection.execute("SELECT COUNT(*) FROM local_albums").fetchone() == (
            1,
        )


def test_catalog_cache_prefixes_cover_every_target_projection() -> None:
    prefixes = set(library_identification_prefixes())

    assert {
        "library:",
        "home_response:",
        "discover_response:",
        "genre_artwork:v2:",
        "compat_library:",
        "local_files_",
        "artist_info:",
        "album_info:",
        "artist_discovery:",
        "discover_queue_enrich:",
        "source_resolution",
    } <= prefixes


def test_search_service_catalog_invalidation_clears_local_ownership_results() -> None:
    SearchService._search_cache["album"] = (1.0, SimpleNamespace())

    SearchService.clear_cached_results()

    assert SearchService._search_cache == {}
