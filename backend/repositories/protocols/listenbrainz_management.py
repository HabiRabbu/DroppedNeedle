from typing import Protocol

from models.library_management_genres import GenreCandidate


class ListenBrainzGenreRepositoryProtocol(Protocol):
    async def get_release_group_genres_batch(
        self, release_group_mbids: list[str]
    ) -> dict[str, tuple[GenreCandidate, ...]]: ...
