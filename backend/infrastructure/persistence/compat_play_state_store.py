"""Compat play-state persistence: play queue, bookmarks and ratings.

Written by the Subsonic shim (savePlayQueue/createBookmark/setRating) but kept
protocol-neutral like ``user_favorites`` so other surfaces can reuse the rows.
Lives in the shared WAL db (FK to auth_users).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path


class CompatPlayStateStore:
    def __init__(self, db_path: Path, write_lock: threading.Lock | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = write_lock or threading.Lock()
        with self._write_lock:
            self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _execute(self, operation, write: bool):
        if write:
            with self._write_lock:
                conn = self._connect()
                try:
                    result = operation(conn)
                    conn.commit()
                    return result
                finally:
                    conn.close()
        conn = self._connect()
        try:
            return operation(conn)
        finally:
            conn.close()

    async def _read(self, operation):
        return await asyncio.to_thread(self._execute, operation, False)

    async def _write(self, operation):
        return await asyncio.to_thread(self._execute, operation, True)

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS compat_play_queues (
                    user_id         TEXT PRIMARY KEY
                                    REFERENCES auth_users(id) ON DELETE CASCADE,
                    file_ids        TEXT NOT NULL,
                    current_file_id TEXT,
                    position_ms     INTEGER NOT NULL DEFAULT 0,
                    changed_at      REAL NOT NULL,
                    changed_by      TEXT
                );
                CREATE TABLE IF NOT EXISTS compat_bookmarks (
                    user_id     TEXT NOT NULL
                                REFERENCES auth_users(id) ON DELETE CASCADE,
                    file_id     TEXT NOT NULL,
                    position_ms INTEGER NOT NULL DEFAULT 0,
                    comment     TEXT,
                    created_at  REAL NOT NULL,
                    changed_at  REAL NOT NULL,
                    PRIMARY KEY (user_id, file_id)
                );
                CREATE TABLE IF NOT EXISTS user_ratings (
                    user_id    TEXT NOT NULL
                               REFERENCES auth_users(id) ON DELETE CASCADE,
                    item_kind  TEXT NOT NULL,
                    item_id    TEXT NOT NULL,
                    rating     INTEGER NOT NULL,
                    changed_at REAL NOT NULL,
                    PRIMARY KEY (user_id, item_kind, item_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ratings_user_kind
                    ON user_ratings(user_id, item_kind);
            """)
            conn.commit()
        finally:
            conn.close()

    # ----- play queue -----

    async def save_queue(
        self,
        user_id: str,
        file_ids: list[str],
        current_file_id: str | None,
        position_ms: int,
        changed_by: str | None,
        changed_at: float,
    ) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO compat_play_queues "
                "(user_id, file_ids, current_file_id, position_ms, changed_at, changed_by) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET file_ids = excluded.file_ids, "
                "current_file_id = excluded.current_file_id, "
                "position_ms = excluded.position_ms, changed_at = excluded.changed_at, "
                "changed_by = excluded.changed_by",
                (user_id, json.dumps(file_ids), current_file_id, position_ms,
                 changed_at, changed_by),
            )

        await self._write(operation)

    async def clear_queue(self, user_id: str) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM compat_play_queues WHERE user_id = ?", (user_id,)
            )

        await self._write(operation)

    async def get_queue(self, user_id: str) -> dict | None:
        def operation(conn: sqlite3.Connection) -> dict | None:
            row = conn.execute(
                "SELECT file_ids, current_file_id, position_ms, changed_at, changed_by "
                "FROM compat_play_queues WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                file_ids = json.loads(row["file_ids"])
            except (TypeError, ValueError):
                file_ids = []
            return {
                "file_ids": [f for f in file_ids if isinstance(f, str)],
                "current_file_id": row["current_file_id"],
                "position_ms": int(row["position_ms"] or 0),
                "changed_at": float(row["changed_at"]),
                "changed_by": row["changed_by"],
            }

        return await self._read(operation)

    # ----- bookmarks -----

    async def set_bookmark(
        self,
        user_id: str,
        file_id: str,
        position_ms: int,
        comment: str | None,
        now: float,
    ) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            # re-bookmarking keeps the original created_at
            conn.execute(
                "INSERT INTO compat_bookmarks "
                "(user_id, file_id, position_ms, comment, created_at, changed_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, file_id) DO UPDATE SET "
                "position_ms = excluded.position_ms, comment = excluded.comment, "
                "changed_at = excluded.changed_at",
                (user_id, file_id, position_ms, comment, now, now),
            )

        await self._write(operation)

    async def remove_bookmark(self, user_id: str, file_id: str) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM compat_bookmarks WHERE user_id = ? AND file_id = ?",
                (user_id, file_id),
            )

        await self._write(operation)

    async def list_bookmarks(self, user_id: str) -> list[dict]:
        def operation(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT file_id, position_ms, comment, created_at, changed_at "
                "FROM compat_bookmarks WHERE user_id = ? ORDER BY changed_at DESC",
                (user_id,),
            ).fetchall()
            return [
                {
                    "file_id": r["file_id"],
                    "position_ms": int(r["position_ms"] or 0),
                    "comment": r["comment"],
                    "created_at": float(r["created_at"]),
                    "changed_at": float(r["changed_at"]),
                }
                for r in rows
            ]

        return await self._read(operation)

    # ----- ratings -----

    async def set_rating(
        self, user_id: str, item_kind: str, item_id: str, rating: int, now: float
    ) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            if rating <= 0:  # Subsonic: rating 0 removes the rating
                conn.execute(
                    "DELETE FROM user_ratings "
                    "WHERE user_id = ? AND item_kind = ? AND item_id = ?",
                    (user_id, item_kind, item_id),
                )
                return
            conn.execute(
                "INSERT INTO user_ratings "
                "(user_id, item_kind, item_id, rating, changed_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, item_kind, item_id) DO UPDATE SET "
                "rating = excluded.rating, changed_at = excluded.changed_at",
                (user_id, item_kind, item_id, rating, now),
            )

        await self._write(operation)

    async def map_ratings_for_items(
        self, user_id: str, item_kind: str, item_ids: list[str]
    ) -> dict[str, int]:
        if not item_ids:
            return {}

        def operation(conn: sqlite3.Connection) -> dict[str, int]:
            placeholders = ", ".join("?" for _ in item_ids)
            rows = conn.execute(
                f"SELECT item_id, rating FROM user_ratings "
                f"WHERE user_id = ? AND item_kind = ? AND item_id IN ({placeholders})",
                (user_id, item_kind, *item_ids),
            ).fetchall()
            return {r["item_id"]: int(r["rating"]) for r in rows}

        return await self._read(operation)
