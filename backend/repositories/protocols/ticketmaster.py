from typing import Protocol

from repositories.ticketmaster_models import TmAttraction, TmEvent


class TicketmasterRepositoryProtocol(Protocol):

    async def search_attractions(self, keyword: str) -> list[TmAttraction]:
        ...

    async def events_for_attraction(self, attraction_id: str) -> list[TmEvent]:
        ...

    async def test_connection(self) -> bool:
        ...
