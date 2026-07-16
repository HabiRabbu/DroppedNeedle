from infrastructure.persistence.compat_bookmark_store import (
    CompatBookmark,
    CompatBookmarkStore,
)


class CompatBookmarkService:
    def __init__(self, store: CompatBookmarkStore) -> None:
        self._store = store

    async def list(self, user_id: str) -> list[CompatBookmark]:
        return await self._store.list(user_id)

    async def upsert(
        self, user_id: str, file_id: str, position_ms: int, comment: str
    ) -> None:
        await self._store.upsert(user_id, file_id, position_ms, comment)

    async def delete(self, user_id: str, file_id: str) -> None:
        await self._store.delete(user_id, file_id)
