from typing import Protocol

from models.library_management_genres import GenreCandidate


class LastFmGenreRepositoryProtocol(Protocol):
    async def get_album_top_genres(
        self, *, artist_name: str, album_title: str
    ) -> tuple[GenreCandidate, ...]: ...

    async def get_artist_top_genres(
        self, *, artist_name: str
    ) -> tuple[GenreCandidate, ...]: ...
