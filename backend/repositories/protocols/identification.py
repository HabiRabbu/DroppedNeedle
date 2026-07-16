from typing import Protocol

from infrastructure.queue.priority_queue import RequestPriority
from models.identification import AlbumCandidate


class IdentificationProviderProtocol(Protocol):
    async def search_album_candidate_ids(
        self,
        query: str,
        limit: int,
        priority: RequestPriority,
    ) -> list[str]: ...

    async def search_recording_candidate_ids(
        self,
        artist: str,
        title: str,
        limit: int,
        priority: RequestPriority,
    ) -> list[str]: ...

    async def get_album_candidate(
        self,
        release_group_mbid: str,
        target_track_count: int,
        priority: RequestPriority,
    ) -> AlbumCandidate | None: ...
