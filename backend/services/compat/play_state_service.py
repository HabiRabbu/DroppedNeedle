"""Play-state service: per-user play queue, bookmarks and ratings.

Persists the Subsonic savePlayQueue/createBookmark/setRating state so a client
can resume across devices. Kinds mirror FavoritesService so ratings unify the
same way stars do.
"""

from __future__ import annotations

import time
from typing import Literal

from infrastructure.persistence.compat_play_state_store import CompatPlayStateStore

RatingKind = Literal["artist", "album", "track"]
_VALID_KINDS = {"artist", "album", "track"}


class CompatPlayStateService:
    def __init__(self, store: CompatPlayStateStore) -> None:
        self._store = store

    # ----- play queue -----

    async def save_queue(
        self,
        user_id: str,
        file_ids: list[str],
        *,
        current_file_id: str | None = None,
        position_ms: int = 0,
        changed_by: str | None = None,
    ) -> None:
        if not file_ids:  # Subsonic: savePlayQueue with no ids clears the queue
            await self._store.clear_queue(user_id)
            return
        await self._store.save_queue(
            user_id, file_ids, current_file_id, max(position_ms, 0),
            changed_by, time.time(),
        )

    async def get_queue(self, user_id: str) -> dict | None:
        """{'file_ids', 'current_file_id', 'position_ms', 'changed_at',
        'changed_by'} or None when nothing is saved."""
        return await self._store.get_queue(user_id)

    # ----- bookmarks -----

    async def set_bookmark(
        self, user_id: str, file_id: str, position_ms: int, comment: str | None = None
    ) -> None:
        await self._store.set_bookmark(
            user_id, file_id, max(position_ms, 0), comment, time.time()
        )

    async def remove_bookmark(self, user_id: str, file_id: str) -> None:
        await self._store.remove_bookmark(user_id, file_id)

    async def list_bookmarks(self, user_id: str) -> list[dict]:
        """{'file_id', 'position_ms', 'comment', 'created_at', 'changed_at'} rows,
        most-recently-changed first."""
        return await self._store.list_bookmarks(user_id)

    # ----- ratings -----

    @staticmethod
    def _check_kind(kind: str) -> None:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Invalid rating kind: {kind!r}")

    async def set_rating(
        self, user_id: str, kind: RatingKind, item_id: str, rating: int
    ) -> None:
        """Persist a 1-5 rating; 0 removes it (Subsonic setRating contract)."""
        self._check_kind(kind)
        await self._store.set_rating(
            user_id, kind, item_id, min(max(rating, 0), 5), time.time()
        )

    async def map_ratings_for_items(
        self, user_id: str, kind: RatingKind, item_ids: list[str]
    ) -> dict[str, int]:
        """Batch {item_id: rating} for cheaply filling userRating."""
        self._check_kind(kind)
        return await self._store.map_ratings_for_items(user_id, kind, item_ids)
