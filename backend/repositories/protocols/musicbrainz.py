from typing import Any, Protocol

from infrastructure.queue.priority_queue import RequestPriority
from models.search import SearchResult
from models.artist import ArtistInfo
from models.album import AlbumInfo


class MusicBrainzRepositoryProtocol(Protocol):

    async def search_artists(
        self,
        query: str,
        limit: int = 10,
        included_types: set[str] | None = None
    ) -> list[SearchResult]:
        ...

    async def search_albums(
        self,
        query: str,
        limit: int = 10,
        included_types: set[str] | None = None,
        included_secondary_types: set[str] | None = None,
        included_statuses: set[str] | None = None
    ) -> list[SearchResult]:
        ...

    async def get_artist_detail(
        self,
        artist_mbid: str,
        included_types: set[str] | None = None,
        included_secondary_types: set[str] | None = None,
        included_statuses: set[str] | None = None
    ) -> ArtistInfo | None:
        ...

    async def get_release_group(
        self,
        release_group_mbid: str
    ) -> AlbumInfo | None:
        ...

    async def get_release(
        self,
        release_mbid: str
    ) -> Any | None:
        ...

    async def get_release_group_id_from_release(
        self,
        release_mbid: str,
        priority: RequestPriority = RequestPriority.BACKGROUND_SYNC
    ) -> str | None:
        ...

    async def get_release_groups_by_artist(
        self,
        artist_mbid: str,
        limit: int = 10
    ) -> list[dict[str, Any]]:
        ...

    async def get_recording_position_on_release(
        self,
        release_id: str,
        recording_mbid: str,
    ) -> tuple[int, int] | None:
        ...
