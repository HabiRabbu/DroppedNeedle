import asyncio
import logging
from typing import Optional

from api.v1.schemas.discovery import (
    DiscoveryAlbum,
    SimilarAlbumsResponse,
    MoreByArtistResponse,
)
from repositories.protocols import ListenBrainzRepositoryProtocol, MusicBrainzRepositoryProtocol, LibraryRepositoryProtocol
from infrastructure.persistence import LibraryDB
from infrastructure.queue.priority_queue import RequestPriority
from services.per_user_client_factory import PerUserClientFactory

logger = logging.getLogger(__name__)


class AlbumDiscoveryService:
    def __init__(
        self,
        listenbrainz_repo: ListenBrainzRepositoryProtocol,
        musicbrainz_repo: MusicBrainzRepositoryProtocol,
        library_db: LibraryDB,
        library_repo: LibraryRepositoryProtocol,
        client_factory: Optional[PerUserClientFactory] = None,
    ):
        self._lb_repo = listenbrainz_repo
        self._mb_repo = musicbrainz_repo
        self._library_db = library_db
        self._library_repo = library_repo
        self._client_factory = client_factory

    async def _resolve_listenbrainz(
        self, user_id: str | None
    ) -> Optional[ListenBrainzRepositoryProtocol]:
        """Per-user ListenBrainz client.

        A known user (user_id present) with a factory always resolves strictly to
        their own connection - never the global repo - so an unlinked user gets
        None. Anonymous/background callers (e.g. album radio) and unit tests (no
        factory) fall back to the legacy global repo when it is configured.
        """
        if self._client_factory is not None and user_id:
            return await self._client_factory.resolve_listenbrainz(user_id)
        return self._lb_repo if self._lb_repo.is_configured() else None

    async def get_similar_albums(
        self,
        album_mbid: str,
        artist_mbid: str,
        count: int = 10,
        user_id: str | None = None,
    ) -> SimilarAlbumsResponse:
        lb_repo = await self._resolve_listenbrainz(user_id)
        if lb_repo is None:
            return SimilarAlbumsResponse(configured=False)

        try:
            similar_artists = await lb_repo.get_similar_artists(artist_mbid, max_similar=5)
            if not similar_artists:
                return SimilarAlbumsResponse(albums=[])

            try:
                library_album_mbids, requested_album_mbids = await asyncio.gather(
                    self._library_repo.get_library_mbids(),
                    self._library_repo.get_requested_mbids()
                )
            except Exception:  # noqa: BLE001
                library_album_mbids = set()
                requested_album_mbids = set()

            tasks = [
                lb_repo.get_artist_top_release_groups(a.artist_mbid, count=3)
                for a in similar_artists[:5]
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            albums: list[DiscoveryAlbum] = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    continue
                artist = similar_artists[i]
                for rg in result:
                    if rg.release_group_mbid and rg.release_group_mbid != album_mbid:
                        mbid_lower = rg.release_group_mbid.lower()
                        albums.append(DiscoveryAlbum(
                            musicbrainz_id=rg.release_group_mbid,
                            title=rg.release_group_name,
                            artist_name=artist.artist_name,
                            artist_id=artist.artist_mbid,
                            in_library=mbid_lower in library_album_mbids,
                            requested=mbid_lower in requested_album_mbids,
                        ))
                        if len(albums) >= count:
                            break
                if len(albums) >= count:
                    break

            return SimilarAlbumsResponse(albums=albums[:count])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to get similar albums for {album_mbid}: {e}")
            return SimilarAlbumsResponse(albums=[])

    async def get_more_by_artist(
        self,
        artist_mbid: str,
        exclude_album_mbid: str,
        count: int = 10,
        priority: RequestPriority = RequestPriority.BACKGROUND_SYNC,
    ) -> MoreByArtistResponse:
        try:
            release_groups = await self._mb_repo.get_release_groups_by_artist(
                artist_mbid,
                limit=count + 5,
                priority=priority,
            )
            if not release_groups:
                return MoreByArtistResponse(albums=[], artist_name="")

            try:
                library_album_mbids, requested_album_mbids = await asyncio.gather(
                    self._library_repo.get_library_mbids(),
                    self._library_repo.get_requested_mbids()
                )
            except Exception:  # noqa: BLE001
                library_album_mbids = set()
                requested_album_mbids = set()

            albums: list[DiscoveryAlbum] = []
            artist_name = ""

            for rg in release_groups:
                rg_mbid = rg.get("id", "")
                if rg_mbid == exclude_album_mbid:
                    continue

                if not artist_name:
                    artist_credit = rg.get("artist-credit", [])
                    if artist_credit:
                        artist_name = artist_credit[0].get("artist", {}).get("name", "")

                year = None
                first_release = rg.get("first-release-date", "")
                if first_release and len(first_release) >= 4:
                    try:
                        year = int(first_release[:4])
                    except ValueError:
                        pass

                mbid_lower = rg_mbid.lower()
                albums.append(DiscoveryAlbum(
                    musicbrainz_id=rg_mbid,
                    title=rg.get("title", "Unknown"),
                    artist_name=artist_name,
                    artist_id=artist_mbid,
                    year=year,
                    in_library=mbid_lower in library_album_mbids,
                    requested=mbid_lower in requested_album_mbids,
                ))

                if len(albums) >= count:
                    break

            return MoreByArtistResponse(albums=albums, artist_name=artist_name)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to get more albums by artist {artist_mbid}: {e}")
            return MoreByArtistResponse(albums=[], artist_name="")
