"""Named discovery download batches: which albums a "Download all" filed, so the
whole batch can be reviewed and reversibly removed later. Only albums the batch
itself requested are ever candidates for removal."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from infrastructure.persistence._database import PersistenceBase


class DiscoveryBatchStore(PersistenceBase):
    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_batches (
                  id             TEXT PRIMARY KEY,
                  user_id        TEXT NOT NULL,
                  name           TEXT NOT NULL,
                  source_section TEXT NOT NULL DEFAULT '',
                  created_at     TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_batch_items (
                  batch_id            TEXT NOT NULL,
                  release_group_mbid  TEXT NOT NULL,
                  artist_mbid         TEXT NOT NULL DEFAULT '',
                  album_name          TEXT NOT NULL DEFAULT '',
                  artist_name         TEXT NOT NULL DEFAULT '',
                  outcome             TEXT NOT NULL DEFAULT 'requested',
                  added_at            TEXT NOT NULL,
                  PRIMARY KEY (batch_id, release_group_mbid)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_discovery_batches_user "
                "ON discovery_batches(user_id, created_at DESC)"
            )
            conn.commit()
        finally:
            conn.close()

    async def create_batch(
        self,
        user_id: str,
        name: str,
        source_section: str,
        items: list[dict[str, Any]],
    ) -> str:
        """Insert the batch and its items (with per-item outcome) in one transaction."""
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO discovery_batches (id, user_id, name, source_section, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (batch_id, user_id, name, source_section, now),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO discovery_batch_items "
                "(batch_id, release_group_mbid, artist_mbid, album_name, artist_name, outcome, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        batch_id,
                        item["release_group_mbid"],
                        item.get("artist_mbid", ""),
                        item.get("album_name", ""),
                        item.get("artist_name", ""),
                        item.get("outcome", "requested"),
                        now,
                    )
                    for item in items
                ],
            )

        await self._write(operation)
        return batch_id

    async def list_batches(self, user_id: str) -> list[dict[str, Any]]:
        def operation(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                "SELECT * FROM discovery_batches WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

        return await self._read(operation)

    async def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        def operation(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute(
                "SELECT * FROM discovery_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            return dict(row) if row else None

        return await self._read(operation)

    async def get_items(self, batch_id: str) -> list[dict[str, Any]]:
        def operation(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                "SELECT * FROM discovery_batch_items WHERE batch_id = ? ORDER BY added_at, album_name",
                (batch_id,),
            ).fetchall()
            return [dict(r) for r in rows]

        return await self._read(operation)

    async def get_items_for_batches(self, batch_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not batch_ids:
            return {}

        def operation(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
            ph = ", ".join("?" for _ in batch_ids)
            rows = conn.execute(
                f"SELECT * FROM discovery_batch_items WHERE batch_id IN ({ph})",
                batch_ids,
            ).fetchall()
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                grouped.setdefault(row["batch_id"], []).append(dict(row))
            return grouped

        return await self._read(operation)

    async def delete_batch(self, batch_id: str) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM discovery_batch_items WHERE batch_id = ?", (batch_id,))
            conn.execute("DELETE FROM discovery_batches WHERE id = ?", (batch_id,))

        await self._write(operation)
