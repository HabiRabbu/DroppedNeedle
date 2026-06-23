"""Library-scan lifecycle persistence (H2/AUD-5).

Owns two tables, kept separate from ``LibraryDB``:
- ``scan_state``: a singleton (``CHECK(id = 1)``) holding scan status + counters.
- ``scan_progress``: a resume ledger, one row per fully-processed path, written
  in BATCHES (AUD-14 - a 10k-file scan must not do 10k row writes) and cleared on
  scan start and on completion/cancel. Resume = re-walk and skip ledgered paths;
  there is no ``last_processed_path`` cursor.

Created in Phase 3 so the scan-status route works; the Phase-4 ``LibraryScanner``
injects this same instance. Constructed with the shared persistence write lock.
"""

import logging
import sqlite3
import time
from typing import Any

from infrastructure.persistence._database import PersistenceBase

logger = logging.getLogger(__name__)

_IDLE_STATE: dict[str, Any] = {
    "status": "idle",
    "total_files": 0,
    "processed_files": 0,
    "matched_files": 0,
    "failed_files": 0,
    "started_at": None,
    "updated_at": None,
}


class ScanStateStore(PersistenceBase):
    """Owns tables: ``scan_state``, ``scan_progress``."""

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_state (
                    id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id = 1),
                    status TEXT NOT NULL DEFAULT 'idle'
                        CHECK(status IN ('idle','scanning','cancelled','error')),
                    total_files INTEGER NOT NULL DEFAULT 0,
                    processed_files INTEGER NOT NULL DEFAULT 0,
                    matched_files INTEGER NOT NULL DEFAULT 0,
                    failed_files INTEGER NOT NULL DEFAULT 0,
                    started_at REAL,
                    updated_at REAL
                )
                """
            )
            conn.execute("CREATE TABLE IF NOT EXISTS scan_progress (path TEXT PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()

    async def get_state(self) -> dict[str, Any]:
        def operation(conn: sqlite3.Connection) -> dict[str, Any]:
            row = conn.execute(
                "SELECT status, total_files, processed_files, matched_files, "
                "failed_files, started_at, updated_at FROM scan_state WHERE id = 1"
            ).fetchone()
            return dict(row) if row is not None else dict(_IDLE_STATE)

        return await self._read(operation)

    async def start(self, total_files: int = 0) -> None:
        """Begin a scan: reset counters to ``scanning`` and clear the resume ledger."""
        now = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM scan_progress")
            conn.execute(
                """
                INSERT INTO scan_state
                    (id, status, total_files, processed_files, matched_files,
                     failed_files, started_at, updated_at)
                VALUES (1, 'scanning', ?, 0, 0, 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = 'scanning', total_files = excluded.total_files,
                    processed_files = 0, matched_files = 0, failed_files = 0,
                    started_at = excluded.started_at, updated_at = excluded.updated_at
                """,
                (total_files, now, now),
            )

        await self._write(operation)

    async def advance(
        self, paths: list[str], *, processed: int, matched: int, failed: int
    ) -> None:
        """Flush a batch of fully-processed paths to the ledger and set counters
        to the supplied absolute totals."""
        now = time.time()
        ledger_rows = [(p,) for p in paths]

        def operation(conn: sqlite3.Connection) -> None:
            if ledger_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO scan_progress (path) VALUES (?)", ledger_rows
                )
            conn.execute(
                "UPDATE scan_state SET processed_files = ?, matched_files = ?, "
                "failed_files = ?, updated_at = ? WHERE id = 1",
                (processed, matched, failed, now),
            )

        await self._write(operation)

    async def set_total(self, total_files: int) -> None:
        """Set only the total-files counter."""
        now = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE scan_state SET total_files = ?, updated_at = ? WHERE id = 1",
                (total_files, now),
            )

        await self._write(operation)

    async def update_counters(
        self, *, processed: int, matched: int, failed: int
    ) -> None:
        """Persist live progress counters without touching the resume ledger."""
        now = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE scan_state SET processed_files = ?, matched_files = ?, "
                "failed_files = ?, updated_at = ? WHERE id = 1",
                (processed, matched, failed, now),
            )

        await self._write(operation)

    async def load_processed(self) -> set[str]:
        def operation(conn: sqlite3.Connection) -> set[str]:
            rows = conn.execute("SELECT path FROM scan_progress").fetchall()
            return {str(row["path"]) for row in rows}

        return await self._read(operation)

    async def is_processed(self, path: str) -> bool:
        def operation(conn: sqlite3.Connection) -> bool:
            return (
                conn.execute(
                    "SELECT 1 FROM scan_progress WHERE path = ? LIMIT 1", (path,)
                ).fetchone()
                is not None
            )

        return await self._read(operation)

    async def complete(self, *, matched: int, failed: int) -> None:
        """Finish a scan: status back to ``idle`` and clear the resume ledger."""
        await self._finish("idle", matched=matched, failed=failed)

    async def cancel(self) -> None:
        await self._finish("cancelled")

    async def fail(self, error: str) -> None:
        # scan_state has no error column; the detail goes to logs (AUD-11).
        logger.error("Library scan failed: %s", error)
        await self._finish("error", clear_ledger=False)

    async def _finish(
        self,
        status: str,
        *,
        matched: int | None = None,
        failed: int | None = None,
        clear_ledger: bool = True,
    ) -> None:
        now = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            if clear_ledger:
                conn.execute("DELETE FROM scan_progress")
            if matched is None:
                conn.execute(
                    "UPDATE scan_state SET status = ?, updated_at = ? WHERE id = 1",
                    (status, now),
                )
            else:
                conn.execute(
                    "UPDATE scan_state SET status = ?, matched_files = ?, "
                    "failed_files = ?, updated_at = ? WHERE id = 1",
                    (status, matched, failed, now),
                )

        await self._write(operation)
