"""Durable per-user Subsonic/OpenSubsonic play queues."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import msgspec

from infrastructure.persistence._database import PersistenceBase


class CompatPlayQueue(msgspec.Struct, frozen=True):
    file_ids: tuple[str, ...] = ()
    current_index: int | None = None
    position_ms: int = 0
    updated_at: float = 0
    changed_by_client: str = ""


class CompatPlayQueueStore(PersistenceBase):
    def __init__(self, db_path: Path, write_lock: threading.Lock) -> None:
        super().__init__(db_path, write_lock)

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS compat_play_queues (
                    user_id TEXT PRIMARY KEY
                        REFERENCES auth_users(id) ON DELETE CASCADE,
                    current_index INTEGER,
                    position_ms INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    changed_by_client TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS compat_play_queue_items (
                    user_id TEXT NOT NULL
                        REFERENCES compat_play_queues(user_id) ON DELETE CASCADE,
                    item_index INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, item_index)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def get(self, user_id: str) -> CompatPlayQueue:
        def operation(conn: sqlite3.Connection) -> CompatPlayQueue:
            row = conn.execute(
                "SELECT current_index, position_ms, updated_at, changed_by_client "
                "FROM compat_play_queues WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return CompatPlayQueue()
            items = conn.execute(
                "SELECT file_id FROM compat_play_queue_items WHERE user_id = ? "
                "ORDER BY item_index",
                (user_id,),
            ).fetchall()
            return CompatPlayQueue(
                file_ids=tuple(item["file_id"] for item in items),
                current_index=row["current_index"],
                position_ms=int(row["position_ms"]),
                updated_at=float(row["updated_at"]),
                changed_by_client=row["changed_by_client"],
            )

        return await self._read(operation)

    async def replace(
        self,
        user_id: str,
        file_ids: tuple[str, ...],
        *,
        current_index: int | None,
        position_ms: int,
        changed_by_client: str,
    ) -> CompatPlayQueue:
        updated_at = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                INSERT INTO compat_play_queues
                    (user_id, current_index, position_ms, updated_at, changed_by_client)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_index = excluded.current_index,
                    position_ms = excluded.position_ms,
                    updated_at = excluded.updated_at,
                    changed_by_client = excluded.changed_by_client
                """,
                (
                    user_id,
                    current_index,
                    position_ms,
                    updated_at,
                    changed_by_client,
                ),
            )
            conn.execute(
                "DELETE FROM compat_play_queue_items WHERE user_id = ?", (user_id,)
            )
            conn.executemany(
                "INSERT INTO compat_play_queue_items (user_id, item_index, file_id) "
                "VALUES (?, ?, ?)",
                [(user_id, index, file_id) for index, file_id in enumerate(file_ids)],
            )

        await self._write(operation)
        return CompatPlayQueue(
            file_ids, current_index, position_ms, updated_at, changed_by_client
        )
