"""``FreeMusicStore`` - persistence for Free Music download tasks (D24).

Deliberately independent of ``DownloadStore``, which phase 02 deletes. One table
in the shared ``library.db``.
"""

import sqlite3
import threading
import time
from pathlib import Path

from infrastructure.persistence._database import PersistenceBase
from models.free_music import FreeMusicStatus, FreeMusicTask

_COLUMNS = (
    "id, user_id, kind, mbid, artist, title, status, identifier, licence_url, "
    "format, files_total, files_completed, bytes_total, bytes_downloaded, "
    "attempts, error, created_at, updated_at"
)


def _row_to_task(row: sqlite3.Row) -> FreeMusicTask:
    return FreeMusicTask(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        mbid=row["mbid"],
        artist=row["artist"],
        title=row["title"],
        status=row["status"],
        identifier=row["identifier"] or "",
        licence_url=row["licence_url"] or "",
        format=row["format"] or "",
        files_total=row["files_total"],
        files_completed=row["files_completed"],
        bytes_total=row["bytes_total"],
        bytes_downloaded=row["bytes_downloaded"],
        attempts=row["attempts"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class FreeMusicStore(PersistenceBase):
    def __init__(self, db_path: Path, write_lock: threading.Lock) -> None:
        super().__init__(db_path, write_lock)

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS free_music_tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('album','track')),
                    mbid TEXT NOT NULL,
                    artist TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN
                        ('searching','downloading','importing','completed','failed','cancelled')),
                    identifier TEXT,
                    licence_url TEXT,
                    format TEXT,
                    files_total INTEGER NOT NULL DEFAULT 0,
                    files_completed INTEGER NOT NULL DEFAULT 0,
                    bytes_total INTEGER NOT NULL DEFAULT 0,
                    bytes_downloaded INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_free_music_user
                    ON free_music_tasks(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_free_music_mbid
                    ON free_music_tasks(mbid);
            """)
            conn.commit()
        finally:
            conn.close()

    async def create(
        self, task_id: str, user_id: str, kind: str, mbid: str, artist: str, title: str
    ) -> None:
        now = time.time()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO free_music_tasks "
                "(id, user_id, kind, mbid, artist, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    user_id,
                    kind,
                    mbid,
                    artist,
                    title,
                    FreeMusicStatus.SEARCHING,
                    now,
                    now,
                ),
            )

        await self._write(operation)

    async def get(self, task_id: str) -> FreeMusicTask | None:
        def operation(conn: sqlite3.Connection) -> FreeMusicTask | None:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM free_music_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return _row_to_task(row) if row else None

        return await self._read(operation)

    async def list_tasks(
        self, *, user_id: str | None = None, limit: int = 50
    ) -> list[FreeMusicTask]:
        """Newest first. ``user_id=None`` lists everyone's (the admin view)."""

        def operation(conn: sqlite3.Connection) -> list[FreeMusicTask]:
            if user_id is None:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM free_music_tasks "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM free_music_tasks WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            return [_row_to_task(r) for r in rows]

        return await self._read(operation)

    async def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        identifier: str | None = None,
        licence_url: str | None = None,
        format: str | None = None,  # noqa: A002 - mirrors the column name
        files_total: int | None = None,
        files_completed: int | None = None,
        bytes_total: int | None = None,
        bytes_downloaded: int | None = None,
        attempts: int | None = None,
        error: str | None = None,
        expected_statuses: tuple[str, ...] | None = None,
    ) -> bool:
        now = time.time()
        fields = {
            "status": status,
            "identifier": identifier,
            "licence_url": licence_url,
            "format": format,
            "files_total": files_total,
            "files_completed": files_completed,
            "bytes_total": bytes_total,
            "bytes_downloaded": bytes_downloaded,
            "attempts": attempts,
            "error": error,
        }
        sets = ["updated_at = ?"]
        params: list = [now]
        for column, value in fields.items():
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        where = "id = ?"
        params.append(task_id)
        if expected_statuses:
            placeholders = ",".join("?" for _ in expected_statuses)
            where += f" AND status IN ({placeholders})"
            params.extend(expected_statuses)

        def operation(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                f"UPDATE free_music_tasks SET {', '.join(sets)} WHERE {where}",
                tuple(params),
            )
            return cursor.rowcount == 1

        return await self._write(operation)

    async def restart_terminal(self, task_id: str) -> bool:
        """Atomically move a failed or cancelled task back to searching.

        The status guard prevents a concurrent history removal from deleting a task
        after retry has claimed it.
        """
        now = time.time()

        def operation(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "UPDATE free_music_tasks SET status = 'searching', identifier = NULL, "
                "licence_url = NULL, format = NULL, files_total = 0, files_completed = 0, "
                "bytes_total = 0, bytes_downloaded = 0, attempts = 0, error = NULL, "
                "updated_at = ? WHERE id = ? AND status IN ('failed','cancelled')",
                (now, task_id),
            )
            return cursor.rowcount == 1

        return await self._write(operation)

    async def cancel_active(self, task_id: str) -> FreeMusicTask | None:
        now = time.time()

        def operation(conn: sqlite3.Connection) -> FreeMusicTask | None:
            changed = conn.execute(
                "UPDATE free_music_tasks SET status = 'cancelled', error = 'Cancelled', "
                "updated_at = ? WHERE id = ? AND status IN ('searching','downloading')",
                (now, task_id),
            ).rowcount
            if changed != 1:
                return None
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM free_music_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return _row_to_task(row)

        return await self._write(operation)

    async def delete_terminal(self, task_id: str) -> FreeMusicTask | None:
        """Delete one terminal history row and return the deleted task."""

        def operation(conn: sqlite3.Connection) -> FreeMusicTask | None:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM free_music_tasks WHERE id = ? "
                "AND status IN ('completed','failed','cancelled')",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            task = _row_to_task(row)
            conn.execute("DELETE FROM free_music_tasks WHERE id = ?", (task_id,))
            return task

        return await self._write(operation)

    async def delete_terminal_tasks(
        self, *, user_id: str | None
    ) -> list[tuple[str, str]]:
        """Delete terminal history for one user, or everyone when ``user_id=None``."""

        def operation(conn: sqlite3.Connection) -> list[tuple[str, str]]:
            where = "status IN ('completed','failed','cancelled')"
            params: tuple[str, ...] = ()
            if user_id is not None:
                where += " AND user_id = ?"
                params = (user_id,)
            rows = conn.execute(
                f"SELECT id, user_id FROM free_music_tasks WHERE {where}", params
            ).fetchall()
            if rows:
                conn.execute(f"DELETE FROM free_music_tasks WHERE {where}", params)
            return [(row["id"], row["user_id"]) for row in rows]

        return await self._write(operation)

    async def fail_stale(self, detail: str) -> int:
        """Startup sweep: a non-terminal task whose coroutine died with the
        process can never finish."""

        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE free_music_tasks SET status = 'failed', error = ?, updated_at = ? "
                "WHERE status NOT IN ('completed','failed','cancelled')",
                (detail, time.time()),
            )
            return cursor.rowcount

        return await self._write(operation)
