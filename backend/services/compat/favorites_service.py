"""Favorites service: per-user stars/favorites, unified across protocols.

A Subsonic star, a Jellyfin ``FavoriteItems`` POST and the native-UI heart all
write the same ``(user_id, kind, item_id)`` row, so a favourite shows everywhere.
"""

from __future__ import annotations

import time
from typing import Literal

from infrastructure.persistence.favorites_store import FavoritesStore

FavoriteKind = Literal["artist", "album", "track"]
_VALID_KINDS = {"artist", "album", "track"}


class FavoritesService:
    def __init__(self, store: FavoritesStore) -> None:
        self._store = store

    @staticmethod
    def _check_kind(kind: str) -> None:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Invalid favorite kind: {kind!r}")

    async def add(self, user_id: str, kind: FavoriteKind, item_id: str) -> None:
        self._check_kind(kind)
        await self._store.add(user_id, kind, item_id, time.time())

    async def remove(self, user_id: str, kind: FavoriteKind, item_id: str) -> None:
        self._check_kind(kind)
        await self._store.remove(user_id, kind, item_id)

    async def is_favorite(self, user_id: str, kind: FavoriteKind, item_id: str) -> bool:
        self._check_kind(kind)
        return await self._store.is_favorite(user_id, kind, item_id)

    async def list(
        self, user_id: str, kind: FavoriteKind
    ) -> list[tuple[str, float]]:
        """(item_id, created_at) pairs, most-recently-starred first."""
        self._check_kind(kind)
        return await self._store.list(user_id, kind)

    async def map_for_items(
        self, user_id: str, kind: FavoriteKind, item_ids: list[str]
    ) -> dict[str, float]:
        """Batch {item_id: starred_at} for cheaply filling starred_at/IsFavorite."""
        self._check_kind(kind)
        return await self._store.map_for_items(user_id, kind, item_ids)
