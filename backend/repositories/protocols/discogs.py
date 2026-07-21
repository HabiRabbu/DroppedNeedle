from typing import Protocol

from infrastructure.queue.priority_queue import RequestPriority
from models.library_contribution import DiscogsRelease, DiscogsReleaseCandidate


class DiscogsRepositoryProtocol(Protocol):
    async def get_release(
        self, release_id: str, *, priority: RequestPriority
    ) -> DiscogsRelease | None: ...

    async def search_releases(
        self,
        query: str,
        *,
        priority: RequestPriority,
        limit: int,
    ) -> list[DiscogsReleaseCandidate]: ...
