from typing import Literal, Protocol

from infrastructure.queue.priority_queue import RequestPriority
from models.library_management_artwork import ArtworkCandidate


class ManagementCoverArtRepositoryProtocol(Protocol):
    async def list_management_artwork(
        self,
        *,
        entity_kind: Literal["release", "release-group"],
        mbid: str,
        download_size: Literal["full", "1200", "500", "250"],
        priority: RequestPriority,
    ) -> tuple[ArtworkCandidate, ...]: ...

    async def download_management_artwork(
        self,
        candidate: ArtworkCandidate,
        *,
        maximum_bytes: int,
        priority: RequestPriority,
    ) -> tuple[bytes, str | None]: ...
