"""Domain 4: MBID resolution and external-service index persistence."""

import logging
import sqlite3
import time
from typing import Any

from infrastructure.persistence._database import PersistenceBase, _normalize

logger = logging.getLogger(__name__)


class MBIDStore(PersistenceBase):
    """Owns tables: ``mbid_resolution_map``, ``ignored_releases``,
    ``jellyfin_mbid_index``, ``navidrome_album_mbid_index``,
    ``navidrome_artist_mbid_index``.
    """

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mbid_resolution_map (
                    source_mbid_lower TEXT PRIMARY KEY,
                    source_mbid TEXT NOT NULL,
                    release_group_mbid TEXT
                )
                """
            )
            # Per-user ignore list (Phase 5): composite PK lets two users independently
            # ignore the same release. Fresh installs get this shape directly; existing
            # single-PK tables are rebuilt by migrate_ignored_releases_to_user() in the
            # lifespan (assigns legacy rows to the first admin).
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ignored_releases (
                    user_id TEXT NOT NULL,
                    release_group_mbid_lower TEXT NOT NULL,
                    release_group_mbid TEXT NOT NULL,
                    artist_mbid TEXT NOT NULL,
                    release_name TEXT NOT NULL,
                    artist_name TEXT NOT NULL,
                    ignored_at REAL NOT NULL,
                    PRIMARY KEY (user_id, release_group_mbid_lower)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jellyfin_mbid_index (
                    mbid_lower TEXT PRIMARY KEY,
                    mbid TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    saved_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS navidrome_album_mbid_index (
                    cache_key TEXT PRIMARY KEY,
                    mbid TEXT,
                    saved_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS navidrome_artist_mbid_index (
                    cache_key TEXT PRIMARY KEY,
                    mbid TEXT,
                    saved_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plex_album_mbid_index (
                    cache_key TEXT PRIMARY KEY,
                    mbid TEXT,
                    saved_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plex_artist_mbid_index (
                    cache_key TEXT PRIMARY KEY,
                    mbid TEXT,
                    saved_at REAL NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def save_mbid_resolution_map(self, mapping: dict[str, str | None]) -> None:
        normalized = {
            source_mbid: value
            for source_mbid, value in mapping.items()
            if isinstance(source_mbid, str) and source_mbid
        }

        def operation(conn: sqlite3.Connection) -> None:
            for source_mbid, resolved_mbid in normalized.items():
                conn.execute(
                    """
                    INSERT INTO mbid_resolution_map (source_mbid_lower, source_mbid, release_group_mbid)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_mbid_lower) DO UPDATE SET
                        source_mbid = excluded.source_mbid,
                        release_group_mbid = excluded.release_group_mbid
                    """,
                    (_normalize(source_mbid), source_mbid, resolved_mbid),
                )

        await self._write(operation)

    async def get_mbid_resolution_map(self, source_mbids: list[str]) -> dict[str, str | None]:
        normalized_mbids = [_normalize(mbid) for mbid in source_mbids if isinstance(mbid, str) and mbid]
        if not normalized_mbids:
            return {}

        def operation(conn: sqlite3.Connection) -> dict[str, str | None]:
            placeholders = ",".join("?" for _ in normalized_mbids)
            rows = conn.execute(
                f"SELECT source_mbid_lower, release_group_mbid FROM mbid_resolution_map WHERE source_mbid_lower IN ({placeholders})",
                tuple(normalized_mbids),
            ).fetchall()
            return {str(row["source_mbid_lower"]): row["release_group_mbid"] for row in rows}

        return await self._read(operation)

    async def add_ignored_release(
        self,
        user_id: str,
        release_group_mbid: str,
        artist_mbid: str,
        release_name: str,
        artist_name: str,
    ) -> None:
        ignored_at = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO ignored_releases (
                    user_id, release_group_mbid_lower, release_group_mbid, artist_mbid,
                    release_name, artist_name, ignored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, release_group_mbid_lower) DO UPDATE SET
                    release_group_mbid = excluded.release_group_mbid,
                    artist_mbid = excluded.artist_mbid,
                    release_name = excluded.release_name,
                    artist_name = excluded.artist_name,
                    ignored_at = excluded.ignored_at
                """,
                (
                    user_id,
                    _normalize(release_group_mbid),
                    release_group_mbid,
                    artist_mbid,
                    release_name,
                    artist_name,
                    ignored_at,
                ),
            )

        await self._write(operation)

    async def get_ignored_release_mbids(self, user_id: str) -> set[str]:
        def operation(conn: sqlite3.Connection) -> set[str]:
            rows = conn.execute(
                "SELECT release_group_mbid_lower FROM ignored_releases WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return {str(row["release_group_mbid_lower"]) for row in rows if row["release_group_mbid_lower"]}

        return await self._read(operation)

    async def get_ignored_releases(self, user_id: str) -> list[dict[str, Any]]:
        def operation(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                "SELECT release_group_mbid, artist_mbid, release_name, artist_name, ignored_at "
                "FROM ignored_releases WHERE user_id = ? ORDER BY ignored_at DESC",
                (user_id,),
            ).fetchall()
            return [
                {
                    "release_group_mbid": row["release_group_mbid"],
                    "artist_mbid": row["artist_mbid"],
                    "release_name": row["release_name"],
                    "artist_name": row["artist_name"],
                    "ignored_at": row["ignored_at"],
                }
                for row in rows
            ]

        return await self._read(operation)

    async def save_jellyfin_mbid_index(self, index: dict[str, str]) -> None:
        saved_at = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM jellyfin_mbid_index")
            for mbid, item_id in index.items():
                if not isinstance(mbid, str) or not mbid or not isinstance(item_id, str) or not item_id:
                    continue
                conn.execute(
                    "INSERT INTO jellyfin_mbid_index (mbid_lower, mbid, item_id, saved_at) VALUES (?, ?, ?, ?)",
                    (_normalize(mbid), mbid, item_id, saved_at),
                )

        await self._write(operation)

    async def load_jellyfin_mbid_index(self, max_age_seconds: int = 3600) -> dict[str, str]:
        def operation(conn: sqlite3.Connection) -> dict[str, str]:
            row = conn.execute("SELECT MAX(saved_at) AS saved_at FROM jellyfin_mbid_index").fetchone()
            if row is None or row["saved_at"] is None:
                return {}
            if time.time() - float(row["saved_at"]) > max(max_age_seconds, 1):
                return {}
            rows = conn.execute("SELECT mbid, item_id FROM jellyfin_mbid_index").fetchall()
            return {str(r["mbid"]): str(r["item_id"]) for r in rows if r["mbid"] and r["item_id"]}

        return await self._read(operation)

    async def clear_jellyfin_mbid_index(self) -> None:
        await self._write(lambda conn: conn.execute("DELETE FROM jellyfin_mbid_index"))

    async def save_navidrome_album_mbid_index(self, index: dict[str, str | None]) -> None:
        saved_at = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM navidrome_album_mbid_index")
            for cache_key, mbid in index.items():
                if not isinstance(cache_key, str) or not cache_key:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO navidrome_album_mbid_index (cache_key, mbid, saved_at) VALUES (?, ?, ?)",
                    (cache_key, mbid, saved_at),
                )

        await self._write(operation)

    async def load_navidrome_album_mbid_index(self, max_age_seconds: int = 86400) -> dict[str, str | None]:
        def operation(conn: sqlite3.Connection) -> dict[str, str | None]:
            row = conn.execute("SELECT MAX(saved_at) AS saved_at FROM navidrome_album_mbid_index").fetchone()
            if row is None or row["saved_at"] is None:
                return {}
            if time.time() - float(row["saved_at"]) > max(max_age_seconds, 1):
                return {}
            rows = conn.execute("SELECT cache_key, mbid FROM navidrome_album_mbid_index").fetchall()
            return {str(r["cache_key"]): (str(r["mbid"]) if r["mbid"] else None) for r in rows if r["cache_key"]}

        return await self._read(operation)

    async def save_navidrome_artist_mbid_index(self, index: dict[str, str | None]) -> None:
        saved_at = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM navidrome_artist_mbid_index")
            for cache_key, mbid in index.items():
                if not isinstance(cache_key, str) or not cache_key:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO navidrome_artist_mbid_index (cache_key, mbid, saved_at) VALUES (?, ?, ?)",
                    (cache_key, mbid, saved_at),
                )

        await self._write(operation)

    async def load_navidrome_artist_mbid_index(self, max_age_seconds: int = 86400) -> dict[str, str | None]:
        def operation(conn: sqlite3.Connection) -> dict[str, str | None]:
            row = conn.execute("SELECT MAX(saved_at) AS saved_at FROM navidrome_artist_mbid_index").fetchone()
            if row is None or row["saved_at"] is None:
                return {}
            if time.time() - float(row["saved_at"]) > max(max_age_seconds, 1):
                return {}
            rows = conn.execute("SELECT cache_key, mbid FROM navidrome_artist_mbid_index").fetchall()
            return {str(r["cache_key"]): (str(r["mbid"]) if r["mbid"] else None) for r in rows if r["cache_key"]}

        return await self._read(operation)

    async def clear_navidrome_mbid_indexes(self) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM navidrome_album_mbid_index")
            conn.execute("DELETE FROM navidrome_artist_mbid_index")

        await self._write(operation)

    async def save_plex_album_mbid_index(self, index: dict[str, str | None]) -> None:
        saved_at = time.time()
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM plex_album_mbid_index")
            for cache_key, mbid in index.items():
                if cache_key:
                    conn.execute(
                        "INSERT OR REPLACE INTO plex_album_mbid_index (cache_key, mbid, saved_at) VALUES (?, ?, ?)",
                        (cache_key, mbid, saved_at),
                    )

        await self._write(operation)

    async def load_plex_album_mbid_index(self, max_age_seconds: int = 86400) -> dict[str, str | None]:
        def operation(conn: sqlite3.Connection) -> dict[str, str | None]:
            row = conn.execute("SELECT MAX(saved_at) AS saved_at FROM plex_album_mbid_index").fetchone()
            if row is None or row["saved_at"] is None:
                return {}
            if time.time() - float(row["saved_at"]) > max(max_age_seconds, 1):
                return {}
            rows = conn.execute("SELECT cache_key, mbid FROM plex_album_mbid_index").fetchall()
            return {str(r["cache_key"]): (str(r["mbid"]) if r["mbid"] else None) for r in rows if r["cache_key"]}

        return await self._read(operation)

    async def save_plex_artist_mbid_index(self, index: dict[str, str | None]) -> None:
        saved_at = time.time()
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM plex_artist_mbid_index")
            for cache_key, mbid in index.items():
                if cache_key:
                    conn.execute(
                        "INSERT OR REPLACE INTO plex_artist_mbid_index (cache_key, mbid, saved_at) VALUES (?, ?, ?)",
                        (cache_key, mbid, saved_at),
                    )

        await self._write(operation)

    async def load_plex_artist_mbid_index(self, max_age_seconds: int = 86400) -> dict[str, str | None]:
        def operation(conn: sqlite3.Connection) -> dict[str, str | None]:
            row = conn.execute("SELECT MAX(saved_at) AS saved_at FROM plex_artist_mbid_index").fetchone()
            if row is None or row["saved_at"] is None:
                return {}
            if time.time() - float(row["saved_at"]) > max(max_age_seconds, 1):
                return {}
            rows = conn.execute("SELECT cache_key, mbid FROM plex_artist_mbid_index").fetchall()
            return {str(r["cache_key"]): (str(r["mbid"]) if r["mbid"] else None) for r in rows if r["cache_key"]}

        return await self._read(operation)

    async def clear_plex_mbid_indexes(self) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM plex_album_mbid_index")
            conn.execute("DELETE FROM plex_artist_mbid_index")

        await self._write(operation)

    async def prune_old_ignored_releases(self, days: int) -> int:
        import time as _time
        cutoff = _time.time() - days * 86400

        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "DELETE FROM ignored_releases WHERE ignored_at < ?",
                (cutoff,),
            )
            return cursor.rowcount

        return await self._write(operation)

    async def migrate_ignored_releases_to_user(self, user_id: str) -> int:
        """One-time (Phase 5): rebuild a legacy single-PK ``ignored_releases`` table
        into the per-user composite-PK shape, assigning all existing (global) rows to
        ``user_id`` (the first admin). Idempotent: no-op once the ``user_id`` column
        exists. Data-preserving - rows are copied, not dropped (AMU-4 intent)."""
        def operation(conn: sqlite3.Connection) -> int:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(ignored_releases)").fetchall()}
            if "user_id" in cols:
                return 0
            conn.execute("ALTER TABLE ignored_releases RENAME TO ignored_releases_legacy")
            conn.execute(
                """
                CREATE TABLE ignored_releases (
                    user_id TEXT NOT NULL,
                    release_group_mbid_lower TEXT NOT NULL,
                    release_group_mbid TEXT NOT NULL,
                    artist_mbid TEXT NOT NULL,
                    release_name TEXT NOT NULL,
                    artist_name TEXT NOT NULL,
                    ignored_at REAL NOT NULL,
                    PRIMARY KEY (user_id, release_group_mbid_lower)
                )
                """
            )
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO ignored_releases (
                    user_id, release_group_mbid_lower, release_group_mbid, artist_mbid,
                    release_name, artist_name, ignored_at
                )
                SELECT ?, release_group_mbid_lower, release_group_mbid, artist_mbid,
                       release_name, artist_name, ignored_at
                FROM ignored_releases_legacy
                """,
                (user_id,),
            )
            conn.execute("DROP TABLE ignored_releases_legacy")
            return cursor.rowcount

        return await self._write(operation)
