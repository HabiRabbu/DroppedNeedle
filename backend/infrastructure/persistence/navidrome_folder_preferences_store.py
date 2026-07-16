"""Per-user outbound Navidrome music-folder preferences."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import msgspec

from infrastructure.persistence._database import PersistenceBase


class NavidromeFolderPreference(msgspec.Struct, frozen=True):
    mode: str = "all"
    selected_folder_ids: tuple[str, ...] = ()
    server_identity: str | None = None
    updated_at: float | None = None


class NavidromeFolderPreferencesStore(PersistenceBase):
    def __init__(self, db_path: Path, write_lock: threading.Lock) -> None:
        super().__init__(db_path, write_lock)

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_navidrome_folder_preferences (
                    user_id TEXT PRIMARY KEY
                        REFERENCES auth_users(id) ON DELETE CASCADE,
                    mode TEXT NOT NULL CHECK (mode IN ('all', 'selected')),
                    selected_ids_json TEXT NOT NULL DEFAULT '[]',
                    server_identity TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def get(self, user_id: str) -> NavidromeFolderPreference:
        def operation(conn: sqlite3.Connection) -> NavidromeFolderPreference:
            row = conn.execute(
                "SELECT mode, selected_ids_json, server_identity, updated_at "
                "FROM user_navidrome_folder_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return NavidromeFolderPreference()
            try:
                raw_ids = json.loads(row["selected_ids_json"])
            except (TypeError, json.JSONDecodeError):
                raw_ids = []
            folder_ids = tuple(
                sorted({value for value in raw_ids if isinstance(value, str)})
            )
            return NavidromeFolderPreference(
                mode=row["mode"],
                selected_folder_ids=folder_ids,
                server_identity=row["server_identity"],
                updated_at=float(row["updated_at"]),
            )

        return await self._read(operation)

    async def set(
        self,
        user_id: str,
        *,
        mode: str,
        selected_folder_ids: tuple[str, ...] = (),
        server_identity: str | None = None,
    ) -> NavidromeFolderPreference:
        canonical = tuple(sorted(set(selected_folder_ids))) if mode == "selected" else ()
        now = time.time()
        encoded = json.dumps(canonical, separators=(",", ":"))

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                INSERT INTO user_navidrome_folder_preferences
                    (user_id, mode, selected_ids_json, server_identity, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    mode = excluded.mode,
                    selected_ids_json = excluded.selected_ids_json,
                    server_identity = excluded.server_identity,
                    updated_at = excluded.updated_at
                """,
                (user_id, mode, encoded, server_identity, now),
            )

        await self._write(operation)
        return NavidromeFolderPreference(mode, canonical, server_identity, now)

    async def delete_for_user(self, user_id: str) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM user_navidrome_folder_preferences WHERE user_id = ?",
                (user_id,),
            )

        await self._write(operation)
