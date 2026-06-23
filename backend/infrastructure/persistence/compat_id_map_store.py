"""Jellyfin id-map persistence: compat_id_map table.

Maps stable 32-hex Jellyfin GUIDs <-> (kind, internal_id). Bijective so
``/Items/{id}`` (which carries no type) resolves. Lives in the shared WAL db.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path


class CompatIdMapStore:
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
                CREATE TABLE IF NOT EXISTS compat_id_map (
                    jf_id       TEXT PRIMARY KEY,
                    kind        TEXT NOT NULL,
                    internal_id TEXT NOT NULL,
                    UNIQUE (kind, internal_id)
                );
            """)
            conn.commit()
        finally:
            conn.close()

    async def get_jf_id(self, kind: str, internal_id: str) -> str | None:
        def operation(conn: sqlite3.Connection) -> str | None:
            row = conn.execute(
                "SELECT jf_id FROM compat_id_map WHERE kind = ? AND internal_id = ?",
                (kind, internal_id),
            ).fetchone()
            return row["jf_id"] if row else None

        return await self._read(operation)

    async def get_mapping(self, jf_id: str) -> tuple[str, str] | None:
        def operation(conn: sqlite3.Connection) -> tuple[str, str] | None:
            row = conn.execute(
                "SELECT kind, internal_id FROM compat_id_map WHERE jf_id = ?",
                (jf_id,),
            ).fetchone()
            return (row["kind"], row["internal_id"]) if row else None

        return await self._read(operation)

    async def insert(self, jf_id: str, kind: str, internal_id: str) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            # deterministic derivation means an existing row is identical; ignore
            # conflicts on either the jf_id PK or the (kind, internal_id) UNIQUE
            conn.execute(
                "INSERT INTO compat_id_map (jf_id, kind, internal_id) "
                "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (jf_id, kind, internal_id),
            )

        await self._write(operation)
