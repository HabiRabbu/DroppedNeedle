from infrastructure.persistence.compat_play_queue_store import (
    CompatPlayQueue,
    CompatPlayQueueStore,
)


class CompatPlayQueueService:
    def __init__(self, store: CompatPlayQueueStore) -> None:
        self._store = store

    async def get(self, user_id: str) -> CompatPlayQueue:
        return await self._store.get(user_id)

    async def replace(
        self,
        user_id: str,
        file_ids: tuple[str, ...],
        *,
        current_index: int | None,
        position_ms: int,
        changed_by_client: str,
    ) -> CompatPlayQueue:
        return await self._store.replace(
            user_id,
            file_ids,
            current_index=current_index,
            position_ms=position_ms,
            changed_by_client=changed_by_client,
        )
