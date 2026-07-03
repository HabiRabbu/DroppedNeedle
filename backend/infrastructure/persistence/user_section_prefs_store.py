"""Per-user Home/Discover section visibility preferences.

Default-on semantics: only *disabled* sections are stored, so sections added
in future releases are automatically on for everyone. Unknown keys left over
from removed sections are ignored on read.
"""

import sqlite3
from datetime import datetime, timezone

from infrastructure.persistence._database import PersistenceBase


class UserSectionPrefsStore(PersistenceBase):
    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_section_prefs (
                  user_id     TEXT NOT NULL,
                  page        TEXT NOT NULL,
                  section_key TEXT NOT NULL,
                  enabled     INTEGER NOT NULL DEFAULT 0,
                  updated_at  TEXT NOT NULL,
                  PRIMARY KEY (user_id, page, section_key)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def get_disabled(self, user_id: str, page: str) -> set[str]:
        def operation(conn: sqlite3.Connection) -> set[str]:
            rows = conn.execute(
                "SELECT section_key FROM user_section_prefs "
                "WHERE user_id = ? AND page = ? AND enabled = 0",
                (user_id, page),
            ).fetchall()
            return {row["section_key"] for row in rows}

        return await self._read(operation)

    async def set_disabled(self, user_id: str, page: str, disabled_keys: set[str]) -> None:
        """Replace the page's disabled set in one transaction."""
        now = datetime.now(timezone.utc).isoformat()

        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM user_section_prefs WHERE user_id = ? AND page = ?",
                (user_id, page),
            )
            conn.executemany(
                "INSERT INTO user_section_prefs (user_id, page, section_key, enabled, updated_at) "
                "VALUES (?, ?, ?, 0, ?)",
                [(user_id, page, key, now) for key in sorted(disabled_keys)],
            )

        await self._write(operation)
