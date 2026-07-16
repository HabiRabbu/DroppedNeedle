"""Durable per-user Subsonic bookmarks."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import msgspec

from infrastructure.persistence._database import PersistenceBase


class CompatBookmark(msgspec.Struct, frozen=True):
    file_id: str
    position_ms: int
    comment: str
    created_at: float
    changed_at: float


class CompatBookmarkStore(PersistenceBase):
    def __init__(self, db_path: Path, write_lock: threading.Lock) -> None:
        super().__init__(db_path, write_lock)

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compat_bookmarks (
                    user_id TEXT NOT NULL
                        REFERENCES auth_users(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL,
                    position_ms INTEGER NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    changed_at REAL NOT NULL,
                    PRIMARY KEY (user_id, file_id)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def list(self, user_id: str) -> list[CompatBookmark]:
        def operation(conn: sqlite3.Connection) -> list[CompatBookmark]:
            rows = conn.execute(
                "SELECT file_id, position_ms, comment, created_at, changed_at "
                "FROM compat_bookmarks WHERE user_id = ? ORDER BY changed_at DESC",
                (user_id,),
            ).fetchall()
            return [
                CompatBookmark(
                    row["file_id"],
                    int(row["position_ms"]),
                    row["comment"],
                    float(row["created_at"]),
                    float(row["changed_at"]),
                )
                for row in rows
            ]

        return await self._read(operation)

    async def upsert(
        self, user_id: str, file_id: str, position_ms: int, comment: str
    ) -> None:
        now = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                INSERT INTO compat_bookmarks
                    (user_id, file_id, position_ms, comment, created_at, changed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, file_id) DO UPDATE SET
                    position_ms = excluded.position_ms,
                    comment = excluded.comment,
                    changed_at = excluded.changed_at
                """,
                (user_id, file_id, position_ms, comment, now, now),
            )

        await self._write(operation)

    async def delete(self, user_id: str, file_id: str) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM compat_bookmarks WHERE user_id = ? AND file_id = ?",
                (user_id, file_id),
            )

        await self._write(operation)
