from typing import Protocol

from repositories.skiddle_models import SkiddleArtist, SkiddleEvent


class SkiddleRepositoryProtocol(Protocol):

    async def search_artists(self, name: str) -> list[SkiddleArtist]:
        ...

    async def events_for_artist(self, artist_id: str) -> list[SkiddleEvent]:
        ...

    async def test_connection(self) -> bool:
        ...
