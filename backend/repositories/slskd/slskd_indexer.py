"""``SlskdIndexer`` - the search side of slskd after the split (D2 / review M6).

``SlskdRepository`` already does Soulseek search, but its ``search_album`` returns
``list[DownloadSearchResult]`` while ``IndexerProtocol.search_album`` returns
``list[IndexerResult]``, and the conformance contract test compares **return
annotations** - so the repo can't satisfy ``IndexerProtocol`` directly. This thin
adapter wraps the repo's search and tags each per-file result as
``IndexerResult{source="soulseek"}``; the orchestrator unwraps ``.soulseek`` back
to ``DownloadSearchResult`` before scoring, so the existing scorers are untouched.

Does NOT use ``from __future__ import annotations`` (the contract test compares
real ``inspect.signature`` objects, including return annotations).
"""

from models.common import ServiceStatus
from repositories.protocols.indexer import IndexerResult

from .slskd_repository import SlskdRepository


class SlskdIndexer:
    def __init__(self, repository: SlskdRepository) -> None:
        self._repo = repository

    @property
    def indexer_name(self) -> str:
        return "soulseek"

    def is_configured(self) -> bool:
        return self._repo.is_configured()

    async def health_check(self) -> ServiceStatus:
        return await self._repo.health_check()

    async def search_album(
        self,
        artist_name: str,
        album_title: str,
        year: int | None = None,
        track_count: int | None = None,
        *,
        timeout: float = 30.0,
    ) -> list[IndexerResult]:
        results = await self._repo.search_album(
            artist_name, album_title, year, track_count, timeout=timeout
        )
        return [IndexerResult(source="soulseek", soulseek=r) for r in results]

    async def search_track(
        self,
        artist_name: str,
        track_title: str,
        album_title: str | None = None,
        duration_seconds: int | None = None,
        *,
        timeout: float = 30.0,
    ) -> list[IndexerResult]:
        results = await self._repo.search_track(
            artist_name, track_title, album_title, duration_seconds, timeout=timeout
        )
        return [IndexerResult(source="soulseek", soulseek=r) for r in results]
