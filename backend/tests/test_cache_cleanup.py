"""Unit tests for cache cleanup gaps — cover deletion, store pruning, genre disk cleanup."""

import asyncio
import json
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Step 1 — CoverDiskCache: delete_by_identifiers, cleanup_expired, demote_orphaned
# ---------------------------------------------------------------------------


@pytest.fixture()
def cover_cache_dir(tmp_path: Path):
    return tmp_path / "covers"


@pytest.fixture()
def cover_disk_cache(cover_cache_dir: Path):
    from repositories.coverart_disk_cache import CoverDiskCache

    return CoverDiskCache(cache_dir=cover_cache_dir)


def _write_cover_files(cache_dir: Path, filename: str, *, meta: dict | None = None):
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{filename}.bin").write_bytes(b"\x89PNG")
    meta_data = meta or {"is_monitored": False}
    (cache_dir / f"{filename}.meta.json").write_text(json.dumps(meta_data))


class TestDeleteByIdentifiers:
    @pytest.mark.asyncio()
    async def test_deletes_matching_files(self, cover_disk_cache, cover_cache_dir):
        from repositories.coverart_disk_cache import get_cache_filename

        h = get_cache_filename("rg_abc", "500")
        _write_cover_files(cover_cache_dir, h)
        assert (cover_cache_dir / f"{h}.bin").exists()

        count = await cover_disk_cache.delete_by_identifiers([("rg_abc", "500")])
        assert count >= 1
        assert not (cover_cache_dir / f"{h}.bin").exists()
        assert not (cover_cache_dir / f"{h}.meta.json").exists()

    @pytest.mark.asyncio()
    async def test_returns_zero_for_missing(self, cover_disk_cache, cover_cache_dir):
        cover_cache_dir.mkdir(parents=True, exist_ok=True)
        count = await cover_disk_cache.delete_by_identifiers([("rg_missing", "500")])
        assert count == 0


class TestCleanupExpired:
    def test_removes_expired_non_monitored(self, cover_disk_cache, cover_cache_dir):
        from repositories.coverart_disk_cache import get_cache_filename

        h = get_cache_filename("rg_old", "250")
        _write_cover_files(
            cover_cache_dir,
            h,
            meta={"is_monitored": False, "expires_at": time.time() - 3600},
        )

        count = cover_disk_cache.cleanup_expired()
        assert count == 1
        assert not (cover_cache_dir / f"{h}.bin").exists()

    def test_keeps_monitored_covers(self, cover_disk_cache, cover_cache_dir):
        from repositories.coverart_disk_cache import get_cache_filename

        h = get_cache_filename("rg_lib", "250")
        _write_cover_files(
            cover_cache_dir,
            h,
            meta={"is_monitored": True},
        )

        count = cover_disk_cache.cleanup_expired()
        assert count == 0
        assert (cover_cache_dir / f"{h}.bin").exists()


class TestDemoteOrphaned:
    def test_demotes_orphaned_monitored(self, cover_disk_cache, cover_cache_dir):
        from repositories.coverart_disk_cache import get_cache_filename

        h = get_cache_filename("rg_gone", "500")
        _write_cover_files(
            cover_cache_dir,
            h,
            meta={"is_monitored": True},
        )

        count = cover_disk_cache.demote_orphaned(set())
        assert count == 1

        meta = json.loads((cover_cache_dir / f"{h}.meta.json").read_text())
        assert meta["is_monitored"] is False
        assert "expires_at" in meta

    def test_keeps_valid_monitored(self, cover_disk_cache, cover_cache_dir):
        from repositories.coverart_disk_cache import get_cache_filename

        h = get_cache_filename("rg_keep", "500")
        _write_cover_files(
            cover_cache_dir,
            h,
            meta={"is_monitored": True},
        )

        count = cover_disk_cache.demote_orphaned({h})
        assert count == 0


# ---------------------------------------------------------------------------
# Step 2 — CoverArtRepository: delete_covers_for_album/artist
# ---------------------------------------------------------------------------


class TestCoverArtRepositoryDeletion:
    @pytest.mark.asyncio()
    async def test_delete_covers_for_album(self, cover_disk_cache, cover_cache_dir):
        from repositories.coverart_disk_cache import get_cache_filename

        mbid = "test-album-mbid"
        for suffix in ("500", "250", "1200", "orig"):
            h = get_cache_filename(f"rg_{mbid}", suffix)
            _write_cover_files(cover_cache_dir, h)

        # Create a minimal mock CoverArtRepository
        from repositories.coverart_repository import CoverArtRepository

        repo = object.__new__(CoverArtRepository)
        repo._disk_cache = cover_disk_cache

        class FakeLRU:
            def __init__(self):
                self._data = {}

            async def evict(self, key):
                self._data.pop(key, None)

        repo._cover_memory_cache = FakeLRU()

        count = await repo.delete_covers_for_album(mbid)
        assert count >= 4

    @pytest.mark.asyncio()
    async def test_delete_covers_for_artist(self, cover_disk_cache, cover_cache_dir):
        from repositories.coverart_disk_cache import get_cache_filename

        mbid = "test-artist-mbid"
        for size in ("250", "500"):
            h = get_cache_filename(f"artist_{mbid}_{size}", "img")
            _write_cover_files(cover_cache_dir, h)
        h_unsuffixed = get_cache_filename(f"artist_{mbid}", "img")
        _write_cover_files(cover_cache_dir, h_unsuffixed)

        from repositories.coverart_repository import CoverArtRepository

        repo = object.__new__(CoverArtRepository)
        repo._disk_cache = cover_disk_cache

        class FakeLRU:
            def __init__(self):
                self._data = {}

            async def evict(self, key):
                self._data.pop(key, None)

        repo._cover_memory_cache = FakeLRU()

        count = await repo.delete_covers_for_artist(mbid)
        assert count >= 3


# ---------------------------------------------------------------------------
# Step 5 — YouTube cascade delete & orphan cleanup
# ---------------------------------------------------------------------------


class TestYouTubeStoreCascade:
    @pytest.fixture()
    def yt_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE youtube_links (album_id TEXT PRIMARY KEY, video_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE youtube_track_links (album_id TEXT, track_number INT, disc_number INT, "
            "album_name TEXT, track_name TEXT, video_id TEXT, artist_name TEXT, embed_url TEXT, created_at TEXT, "
            "PRIMARY KEY (album_id, disc_number, track_number))"
        )
        conn.execute("INSERT INTO youtube_links VALUES ('a1', 'v1')")
        conn.execute(
            "INSERT INTO youtube_track_links VALUES ('a1', 1, 1, 'Album', 'Track', 'v1', 'Artist', 'url', '2024-01-01')"
        )
        conn.execute(
            "INSERT INTO youtube_track_links VALUES ('orphan', 2, 1, 'Album', 'Track', 'v2', 'Artist', 'url', '2024-01-01')"
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.mark.asyncio()
    async def test_delete_youtube_link_cascades(self, yt_db):
        from infrastructure.persistence.youtube_store import YouTubeStore

        store = YouTubeStore.__new__(YouTubeStore)
        store._db_path = str(yt_db)
        store._write_lock = asyncio.Lock()

        async def _write(fn):
            conn = sqlite3.connect(str(yt_db))
            try:
                result = fn(conn)
                conn.commit()
                return result
            finally:
                conn.close()

        store._write = _write

        await store.delete_youtube_link("a1")

        conn = sqlite3.connect(str(yt_db))
        assert conn.execute("SELECT COUNT(*) FROM youtube_links").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM youtube_track_links WHERE album_id='a1'").fetchone()[0] == 0
        conn.close()

    @pytest.mark.asyncio()
    async def test_delete_orphaned_track_links(self, yt_db):
        from infrastructure.persistence.youtube_store import YouTubeStore

        store = YouTubeStore.__new__(YouTubeStore)
        store._db_path = str(yt_db)
        store._write_lock = asyncio.Lock()

        async def _write(fn):
            conn = sqlite3.connect(str(yt_db))
            try:
                result = fn(conn)
                conn.commit()
                return result
            finally:
                conn.close()

        store._write = _write

        count = await store.delete_orphaned_track_links()
        assert count == 1

        conn = sqlite3.connect(str(yt_db))
        remaining = conn.execute("SELECT album_id FROM youtube_track_links").fetchall()
        assert all(r[0] != "orphan" for r in remaining)
        conn.close()


# ---------------------------------------------------------------------------
# Step 6 — RequestHistoryStore.prune_old_terminal_requests
# ---------------------------------------------------------------------------


class TestRequestHistoryPruning:
    @pytest.fixture()
    def rh_db(self, tmp_path):
        db_path = tmp_path / "rh.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE request_history ("
            "musicbrainz_id_lower TEXT PRIMARY KEY, status TEXT, "
            "requested_at TEXT, completed_at TEXT, download_task_id TEXT)"
        )
        old_date = "2020-01-01T00:00:00"
        recent_date = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO request_history VALUES (?, ?, ?, ?, ?)",
            ("old-imported", "imported", old_date, old_date, "1"),
        )
        conn.execute(
            "INSERT INTO request_history VALUES (?, ?, ?, ?, ?)",
            ("old-failed", "failed", old_date, old_date, "2"),
        )
        conn.execute(
            "INSERT INTO request_history VALUES (?, ?, ?, ?, ?)",
            ("active-pending", "pending", recent_date, None, "3"),
        )
        conn.execute(
            "INSERT INTO request_history VALUES (?, ?, ?, ?, ?)",
            ("recent-imported", "imported", recent_date, recent_date, "4"),
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.mark.asyncio()
    async def test_prunes_old_terminal(self, rh_db):
        from infrastructure.persistence.request_history import RequestHistoryStore

        store = RequestHistoryStore.__new__(RequestHistoryStore)
        store._db_path = str(rh_db)
        store._write_lock = asyncio.Lock()

        async def _write(fn):
            conn = sqlite3.connect(str(rh_db))
            conn.row_factory = sqlite3.Row
            try:
                result = fn(conn)
                conn.commit()
                return result
            finally:
                conn.close()

        store._write = _write

        count = await store.prune_old_terminal_requests(days=30)
        assert count == 2

        conn = sqlite3.connect(str(rh_db))
        remaining = conn.execute("SELECT musicbrainz_id_lower FROM request_history").fetchall()
        ids = {r[0] for r in remaining}
        assert "active-pending" in ids
        assert "recent-imported" in ids
        assert "old-imported" not in ids
        conn.close()


# ---------------------------------------------------------------------------
# Step 8 — AdvancedSettings new fields
# ---------------------------------------------------------------------------


class TestAdvancedSettingsNewFields:
    def test_default_values(self):
        from api.v1.schemas.advanced_settings import AdvancedSettings

        settings = AdvancedSettings()
        assert settings.request_history_retention_days == 180
        assert settings.ignored_releases_retention_days == 365
        assert settings.orphan_cover_demote_interval_hours == 24
        assert settings.store_prune_interval_hours == 6

    def test_validation_rejects_out_of_range(self):
        from api.v1.schemas.advanced_settings import AdvancedSettings
        import msgspec

        with pytest.raises(msgspec.ValidationError):
            AdvancedSettings(request_history_retention_days=5)

        with pytest.raises(msgspec.ValidationError):
            AdvancedSettings(orphan_cover_demote_interval_hours=0)


# ---------------------------------------------------------------------------
# Step 9 — GenreService.clear_disk_cache
# ---------------------------------------------------------------------------


class TestGenreDiskCacheClear:
    def test_clears_json_files(self, tmp_path):
        genre_dir = tmp_path / "genre_sections"
        genre_dir.mkdir()
        (genre_dir / "listenbrainz.json").write_text("{}")
        (genre_dir / "lastfm.json").write_text("{}")

        from services.home.genre_service import GenreService

        svc = object.__new__(GenreService)
        svc._genre_section_dir = genre_dir

        count = svc.clear_disk_cache()
        assert count == 2
        assert not list(genre_dir.glob("*.json"))

    def test_returns_zero_for_missing_dir(self, tmp_path):
        from services.home.genre_service import GenreService

        svc = object.__new__(GenreService)
        svc._genre_section_dir = tmp_path / "nonexistent"

        assert svc.clear_disk_cache() == 0


# ---------------------------------------------------------------------------
# Step 11 — HomeService.clear_genre_disk_cache facade
# ---------------------------------------------------------------------------


class TestHomeServiceGenreFacade:
    def test_delegates_to_genre_service(self):
        from services.home.facade import HomeService

        svc = object.__new__(HomeService)
        mock_genre = MagicMock()
        mock_genre.clear_disk_cache.return_value = 3
        svc._genre = mock_genre

        result = svc.clear_genre_disk_cache()
        assert result == 3
        mock_genre.clear_disk_cache.assert_called_once()
