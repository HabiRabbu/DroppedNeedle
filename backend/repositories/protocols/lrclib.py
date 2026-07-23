from typing import Protocol

from models.library_management_enrichment import LyricsLookupResult


class LrclibRepositoryProtocol(Protocol):
    async def get_exact_lyrics(
        self,
        *,
        track_name: str,
        artist_name: str,
        album_name: str,
        duration_seconds: int,
    ) -> LyricsLookupResult: ...
