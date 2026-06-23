import asyncio
import copy
import logging
import msgspec
from typing import Any, Optional, TYPE_CHECKING
from api.v1.schemas.artist import ArtistInfo, ArtistExtendedInfo, ArtistReleases, ExternalLink, ReleaseItem
from repositories.protocols import MusicBrainzRepositoryProtocol, LibraryRepositoryProtocol, WikidataRepositoryProtocol
from services.preferences_service import PreferencesService
from services.artist_utils import (
    extract_tags,
    extract_aliases,
    extract_life_span,
    extract_external_links,
    categorize_release_groups,
    extract_wiki_info,
    build_base_artist_info,
)
from infrastructure.cache.cache_keys import ARTIST_INFO_PREFIX
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.cache.disk_cache import DiskMetadataCache
from infrastructure.validators import validate_mbid
from core.exceptions import ResourceNotFoundError
from services.audiodb_image_service import AudioDBImageService
from repositories.audiodb_models import AudioDBArtistImages

if TYPE_CHECKING:
    from infrastructure.persistence import LibraryDB

logger = logging.getLogger(__name__)


class ArtistService:
    def __init__(
        self,
        mb_repo: MusicBrainzRepositoryProtocol,
        library_repo: LibraryRepositoryProtocol,
        wikidata_repo: WikidataRepositoryProtocol,
        preferences_service: PreferencesService,
        memory_cache: CacheInterface,
        disk_cache: DiskMetadataCache,
        audiodb_image_service: AudioDBImageService | None = None,
        audiodb_browse_queue: Any = None,
        library_db: 'LibraryDB | None' = None,
    ):
        self._mb_repo = mb_repo
        self._library_repo = library_repo
        self._wikidata_repo = wikidata_repo
        self._preferences_service = preferences_service
        self._cache = memory_cache
        self._disk_cache = disk_cache
        self._audiodb_image_service = audiodb_image_service
        self._audiodb_browse_queue = audiodb_browse_queue
        self._library_db = library_db
        self._artist_in_flight: dict[str, asyncio.Future[ArtistInfo]] = {}
        self._artist_basic_in_flight: dict[str, asyncio.Future[ArtistInfo]] = {}

    async def _get_library_cache_mbids(self) -> set[str]:
        if self._library_db is None:
            return set()
        try:
            raw = await self._library_db.get_all_album_mbids()
            return {m.lower() for m in raw if m}
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to read library cache MBIDs: %s", e)
            return set()

    async def _revalidate_library_status(self, artist_info: ArtistInfo) -> ArtistInfo:
        cache_mbids = await self._get_library_cache_mbids()
        try:
            library_mbids = await self._library_repo.get_library_mbids(include_release_ids=True)
        except Exception:  # noqa: BLE001
            library_mbids = set()
        all_mbids = library_mbids | cache_mbids
        if not all_mbids:
            return artist_info

        result = copy.deepcopy(artist_info)
        for release_list in (result.albums, result.singles, result.eps):
            if not release_list:
                continue
            for release in release_list:
                if isinstance(release, dict):
                    rid = (release.get("id") or "").lower()
                else:
                    rid = (release.id or "").lower()
                if not rid:
                    continue
                new_in_library = rid in all_mbids
                old_in_library = release.get("in_library", False) if isinstance(release, dict) else release.in_library
                if new_in_library != old_in_library:
                    if isinstance(release, dict):
                        release["in_library"] = new_in_library
                        if new_in_library and release.get("requested"):
                            release["requested"] = False
                    else:
                        release.in_library = new_in_library
                        if new_in_library and release.requested:
                            release.requested = False

        artist_mbids = await self._get_library_artist_mbids()
        new_artist_in_library = result.musicbrainz_id and result.musicbrainz_id.lower() in artist_mbids
        if new_artist_in_library != result.in_library:
            result.in_library = new_artist_in_library

        return result

    async def _get_library_artist_mbids(self) -> set[str]:
        if self._library_db is None:
            return set()
        try:
            raw = await self._library_db.get_all_artist_mbids()
            return {m.lower() for m in raw if m}
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to read library artist cache MBIDs: %s", e)
            return set()

    async def _apply_audiodb_artist_images(
        self,
        artist_info: ArtistInfo,
        mbid: str,
        name: str | None,
        *,
        allow_fetch: bool = False,
        is_monitored: bool = False,
    ) -> ArtistInfo:
        if self._audiodb_image_service is None:
            return artist_info
        try:
            images: AudioDBArtistImages | None
            if allow_fetch:
                images = await self._audiodb_image_service.fetch_and_cache_artist_images(
                    mbid, name, is_monitored=is_monitored,
                )
            else:
                images = await self._audiodb_image_service.get_cached_artist_images(mbid)
            if images is None or images.is_negative:
                if not allow_fetch and images is None and self._audiodb_browse_queue:
                    settings = self._preferences_service.get_advanced_settings()
                    if settings.audiodb_enabled:
                        await self._audiodb_browse_queue.enqueue("artist", mbid, name=name)
                return artist_info
            if not artist_info.fanart_url and images.fanart_url:
                artist_info.fanart_url = images.fanart_url
            if not artist_info.banner_url and images.banner_url:
                artist_info.banner_url = images.banner_url
            if images.thumb_url:
                artist_info.thumb_url = images.thumb_url
            if images.fanart_url_2:
                artist_info.fanart_url_2 = images.fanart_url_2
            if images.fanart_url_3:
                artist_info.fanart_url_3 = images.fanart_url_3
            if images.fanart_url_4:
                artist_info.fanart_url_4 = images.fanart_url_4
            if images.wide_thumb_url:
                artist_info.wide_thumb_url = images.wide_thumb_url
            if images.logo_url:
                artist_info.logo_url = images.logo_url
            if images.clearart_url:
                artist_info.clearart_url = images.clearart_url
            if images.cutout_url:
                artist_info.cutout_url = images.cutout_url
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to apply AudioDB images for artist %s: %s", mbid[:8], e)
        return artist_info

    async def get_artist_info(
        self,
        artist_id: str,
        library_artist_mbids: set[str] = None,
        library_album_mbids: dict[str, Any] = None
    ) -> ArtistInfo:
        try:
            artist_id = validate_mbid(artist_id, "artist")
        except ValueError as e:
            logger.error(f"Invalid artist MBID: {e}")
            raise
        try:
            cached = await self._get_cached_artist(artist_id)
            if cached:
                cached = await self._revalidate_library_status(cached)
                cached = await self._apply_audiodb_artist_images(
                    cached, artist_id, cached.name,
                    allow_fetch=False, is_monitored=cached.in_library,
                )
                return cached

            if artist_id in self._artist_in_flight:
                return await asyncio.shield(self._artist_in_flight[artist_id])

            loop = asyncio.get_running_loop()
            future: asyncio.Future[ArtistInfo] = loop.create_future()
            self._artist_in_flight[artist_id] = future
            try:
                artist_info = await self._do_get_artist_info(artist_id, library_artist_mbids, library_album_mbids)
                if not future.done():
                    future.set_result(artist_info)
                return artist_info
            except BaseException as exc:
                if not future.done():
                    future.set_exception(exc)
                raise
            finally:
                self._artist_in_flight.pop(artist_id, None)
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"API call failed for artist {artist_id}: {e}")
            raise ResourceNotFoundError(f"Failed to get artist info: {e}")

    async def _do_get_artist_info(
        self, artist_id: str,
        library_artist_mbids: set[str] | None,
        library_album_mbids: dict[str, Any] | None,
    ) -> ArtistInfo:
        artist_info = await self._build_artist_from_musicbrainz(artist_id, library_artist_mbids, library_album_mbids)
        artist_info = await self._apply_audiodb_artist_images(
            artist_info, artist_id, artist_info.name,
            allow_fetch=False, is_monitored=artist_info.in_library,
        )
        await self._save_artist_to_cache(artist_id, artist_info)
        return artist_info

    async def _build_artist_from_musicbrainz(
        self,
        artist_id: str,
        library_artist_mbids: set[str] = None,
        library_album_mbids: dict[str, Any] = None,
        include_extended: bool = True,
        include_releases: bool = True,
    ) -> ArtistInfo:
        mb_artist, library_mbids, album_mbids, requested_mbids = await self._fetch_artist_data(
            artist_id, library_artist_mbids, library_album_mbids
        )
        in_library = artist_id.lower() in library_mbids
        albums, singles, eps = (await self._get_categorized_releases(mb_artist, album_mbids, requested_mbids)) if include_releases else ([], [], [])
        description, image = (await self._fetch_wikidata_info(mb_artist)) if include_extended else (None, None)
        info = build_base_artist_info(
            mb_artist, artist_id, in_library,
            extract_tags(mb_artist), extract_aliases(mb_artist), extract_life_span(mb_artist),
            self._build_external_links(mb_artist), albums, singles, eps, description, image
        )
        return ArtistInfo(**info)

    async def get_artist_info_basic(self, artist_id: str) -> ArtistInfo:
        artist_id = validate_mbid(artist_id, "artist")
        cached = await self._get_cached_artist(artist_id)
        if cached:
            cached = await self._apply_audiodb_artist_images(
                cached, artist_id, cached.name, allow_fetch=False,
            )
            await self._refresh_library_flags(cached)
            return cached

        if artist_id in self._artist_basic_in_flight:
            return await asyncio.shield(self._artist_basic_in_flight[artist_id])

        loop = asyncio.get_running_loop()
        future: asyncio.Future[ArtistInfo] = loop.create_future()
        self._artist_basic_in_flight[artist_id] = future
        try:
            artist_info = await self._build_artist_from_musicbrainz(artist_id, include_extended=False, include_releases=False)
            artist_info = await self._apply_audiodb_artist_images(
                artist_info, artist_id, artist_info.name, allow_fetch=False,
            )
            await self._refresh_library_flags(artist_info)
            await self._save_artist_to_cache(artist_id, artist_info)
            if not future.done():
                future.set_result(artist_info)
            return artist_info
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            self._artist_basic_in_flight.pop(artist_id, None)

    async def _refresh_library_flags(self, artist_info: ArtistInfo) -> None:
        if not self._library_repo.is_configured():
            return
        try:
            library_mbids, requested_mbids, artist_mbids = await asyncio.gather(
                self._library_repo.get_library_mbids(include_release_ids=False),
                self._library_repo.get_requested_mbids(),
                self._library_repo.get_artist_mbids(),
            )
            for release_list in (artist_info.albums, artist_info.singles, artist_info.eps):
                for rg in release_list:
                    rg_id = (rg.id or "").lower()
                    if not rg_id:
                        continue
                    rg.in_library = rg_id in library_mbids
                    rg.requested = rg_id in requested_mbids and not rg.in_library
            mbid_lower = artist_info.musicbrainz_id.lower()
            artist_info.in_library = mbid_lower in artist_mbids
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to refresh library flags: {e}")

    async def _get_cached_artist(self, artist_id: str) -> Optional[ArtistInfo]:
        cache_key = f"{ARTIST_INFO_PREFIX}{artist_id}"
        cached_info = await self._cache.get(cache_key)
        if cached_info:
            return cached_info
        disk_data = await self._disk_cache.get_artist(artist_id)
        if disk_data:
            try:
                artist_info = msgspec.convert(disk_data, ArtistInfo, strict=False)
            except (msgspec.ValidationError, TypeError, ValueError) as e:
                logger.warning(f"Corrupt disk cache for artist {artist_id[:8]}, clearing: {e}")
                await self._disk_cache.delete_artist(artist_id)
                return None
            ttl = self._get_artist_ttl(artist_info.in_library)
            await self._cache.set(cache_key, artist_info, ttl_seconds=ttl)
            return artist_info
        return None

    async def _save_artist_to_cache(self, artist_id: str, artist_info: ArtistInfo) -> None:
        cache_key = f"{ARTIST_INFO_PREFIX}{artist_id}"
        ttl = self._get_artist_ttl(artist_info.in_library)
        await self._cache.set(cache_key, artist_info, ttl_seconds=ttl)
        await self._disk_cache.set_artist(
            artist_id, artist_info,
            is_monitored=artist_info.in_library,
            ttl_seconds=ttl if not artist_info.in_library else None
        )

    def _get_artist_ttl(self, in_library: bool) -> int:
        advanced_settings = self._preferences_service.get_advanced_settings()
        return advanced_settings.cache_ttl_artist_library if in_library else advanced_settings.cache_ttl_artist_non_library
    
    async def get_artist_extended_info(self, artist_id: str) -> ArtistExtendedInfo:
        try:
            artist_id = validate_mbid(artist_id, "artist")
            cache_key = f"{ARTIST_INFO_PREFIX}{artist_id}"
            cached_info = await self._cache.get(cache_key)
            if cached_info and cached_info.description is not None:
                return ArtistExtendedInfo(description=cached_info.description, image=cached_info.image)
            mb_artist = await self._mb_repo.get_artist_by_id(artist_id)
            if not mb_artist:
                raise ResourceNotFoundError("Artist not found")
            description, image = await self._fetch_wikidata_info(mb_artist)
            if cached_info:
                cached_info.description = description
                cached_info.image = image
                await self._save_artist_to_cache(artist_id, cached_info)
            return ArtistExtendedInfo(description=description, image=image)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error fetching extended artist info for {artist_id}: {e}")
            return ArtistExtendedInfo(description=None, image=None)
    
    async def get_artist_releases(
        self,
        artist_id: str,
        offset: int = 0,
        limit: int = 50
    ) -> ArtistReleases:
        try:
            album_mbids, requested_mbids, cache_mbids = await asyncio.gather(
                self._library_repo.get_library_mbids(include_release_ids=True),
                self._library_repo.get_requested_mbids(),
                self._get_library_cache_mbids(),
            )
            album_mbids = album_mbids | cache_mbids

            prefs = self._preferences_service.get_preferences()
            included_primary_types = set(t.lower() for t in prefs.primary_types)
            included_secondary_types = set(t.lower() for t in prefs.secondary_types)

            return await self._filter_aware_release_page(
                artist_id, offset, limit, album_mbids, requested_mbids,
                included_primary_types, included_secondary_types,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error fetching releases for artist {artist_id} at offset {offset}: {e}")
            return ArtistReleases(
                albums=[], singles=[], eps=[],
                offset=offset, limit=limit, returned_count=0,
                next_offset=None, has_more=False, source_total_count=None,
            )

    async def _filter_aware_release_page(
        self,
        artist_id: str,
        offset: int,
        limit: int,
        album_mbids: set[str],
        requested_mbids: set[str],
        included_primary_types: set[str],
        included_secondary_types: set[str],
    ) -> ArtistReleases:
        if not included_primary_types:
            return ArtistReleases(
                albums=[], singles=[], eps=[],
                offset=offset, limit=limit, returned_count=0,
                next_offset=None, has_more=False, source_total_count=None,
            )

        _SCAN_BATCH = 100
        _MAX_SCAN_BATCHES = 2
        seen_mbids: set[str] = set()
        all_albums: list[ReleaseItem] = []
        all_singles: list[ReleaseItem] = []
        all_eps: list[ReleaseItem] = []

        raw_offset = offset
        source_total: int | None = None
        batches_scanned = 0

        while batches_scanned < _MAX_SCAN_BATCHES:
            release_groups, mb_total = await self._mb_repo.get_artist_release_groups(
                artist_id, raw_offset, _SCAN_BATCH
            )
            if source_total is None:
                source_total = mb_total

            if not release_groups:
                break

            temp_artist = {"release-group-list": release_groups}
            page_albums, page_singles, page_eps = categorize_release_groups(
                temp_artist, album_mbids, included_primary_types,
                included_secondary_types, requested_mbids,
            )

            for item in page_albums:
                if item.id and item.id not in seen_mbids:
                    seen_mbids.add(item.id)
                    all_albums.append(item)
            for item in page_singles:
                if item.id and item.id not in seen_mbids:
                    seen_mbids.add(item.id)
                    all_singles.append(item)
            for item in page_eps:
                if item.id and item.id not in seen_mbids:
                    seen_mbids.add(item.id)
                    all_eps.append(item)

            raw_offset += len(release_groups)
            batches_scanned += 1

            total_collected = len(all_albums) + len(all_singles) + len(all_eps)
            if total_collected >= limit:
                break
            if raw_offset >= mb_total:
                break

        for lst in (all_albums, all_singles, all_eps):
            lst.sort(key=lambda x: (x.year is None, -(x.year or 0)))

        returned_count = len(all_albums) + len(all_singles) + len(all_eps)

        has_more = raw_offset < (source_total or 0)

        next_offset = raw_offset if has_more else None

        return ArtistReleases(
            albums=all_albums,
            singles=all_singles,
            eps=all_eps,
            offset=offset,
            limit=limit,
            returned_count=returned_count,
            next_offset=next_offset,
            has_more=has_more,
            source_total_count=source_total,
        )
    
    async def _fetch_artist_data(
        self,
        artist_id: str,
        library_artist_mbids: set[str] = None,
        library_album_mbids: dict[str, Any] = None
    ) -> tuple[dict, set[str], set[str], set[str]]:
        if library_artist_mbids is not None and library_album_mbids is not None:
            mb_artist = await self._mb_repo.get_artist_by_id(artist_id)
            library_mbids = library_artist_mbids
            album_mbids = library_album_mbids
            try:
                requested_mbids = await self._library_repo.get_requested_mbids()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Lidarr unavailable, proceeding without requested data: {exc}")
                requested_mbids = set()
        else:
            mb_artist, *library_results = await asyncio.gather(
                self._mb_repo.get_artist_by_id(artist_id),
                self._library_repo.get_artist_mbids(),
                self._library_repo.get_library_mbids(include_release_ids=True),
                self._library_repo.get_requested_mbids(),
                return_exceptions=True,
            )
            if isinstance(mb_artist, BaseException):
                logger.error(f"Error fetching artist data for {artist_id}: {mb_artist}")
                raise ResourceNotFoundError(f"Failed to fetch artist: {mb_artist}")
            library_failed = any(isinstance(r, BaseException) for r in library_results)
            if library_failed:
                logger.warning(f"Lidarr unavailable for artist {artist_id}, proceeding with MusicBrainz data only")
            library_mbids = library_results[0] if not isinstance(library_results[0], BaseException) else set()
            album_mbids = library_results[1] if not isinstance(library_results[1], BaseException) else set()
            requested_mbids = library_results[2] if not isinstance(library_results[2], BaseException) else set()

        cache_mbids = await self._get_library_cache_mbids()
        album_mbids = album_mbids | cache_mbids

        if not mb_artist:
            raise ResourceNotFoundError("Artist not found")

        return mb_artist, library_mbids, album_mbids, requested_mbids
    
    def _build_external_links(self, mb_artist: dict[str, Any]) -> list[ExternalLink]:
        external_links_data = extract_external_links(mb_artist)
        return [
            ExternalLink(type=link["type"], url=link["url"], label=link["label"])
            for link in external_links_data
        ]

    async def _get_categorized_releases(
        self,
        mb_artist: dict[str, Any],
        album_mbids: set[str],
        requested_mbids: set[str] = None,
    ) -> tuple[list[ReleaseItem], list[ReleaseItem], list[ReleaseItem]]:
        prefs = self._preferences_service.get_preferences()
        included_primary_types = set(t.lower() for t in prefs.primary_types)
        included_secondary_types = set(t.lower() for t in prefs.secondary_types)
        return categorize_release_groups(
            mb_artist,
            album_mbids,
            included_primary_types,
            included_secondary_types,
            requested_mbids or set(),
        )
    
    async def _fetch_wikidata_info(self, mb_artist: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        wikidata_id, wiki_urls = self._extract_wiki_info(mb_artist)
        
        tasks = []
        if wiki_urls:
            tasks.append(self._wikidata_repo.get_wikipedia_extract(wiki_urls[0]))
        else:
            tasks.append(asyncio.create_task(asyncio.sleep(0)))
        
        if wikidata_id:
            tasks.append(self._wikidata_repo.get_artist_image_from_wikidata(wikidata_id))
        else:
            tasks.append(asyncio.create_task(asyncio.sleep(0)))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        description = results[0] if len(results) > 0 and not isinstance(results[0], Exception) and results[0] else None
        image = results[1] if len(results) > 1 and not isinstance(results[1], Exception) and results[1] else None
        
        return description, image
    
    def _extract_wiki_info(self, mb_artist: dict[str, Any]) -> tuple[Optional[str], list[str]]:
        return extract_wiki_info(mb_artist, self._wikidata_repo.get_wikidata_id_from_url)
