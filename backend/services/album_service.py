import logging
import asyncio
from typing import Optional, TYPE_CHECKING
import msgspec
from api.v1.schemas.album import AlbumInfo, AlbumBasicInfo, AlbumTracksInfo, Track
from repositories.protocols import (
    LibraryRepositoryProtocol,
    MusicBrainzRepositoryProtocol,
)
from services.preferences_service import PreferencesService
from services.album_utils import (
    find_primary_release,
    get_ranked_releases,
    extract_artist_info,
    extract_tracks,
    extract_label,
    build_album_basic_info,
    mb_to_basic_info,
)
from infrastructure.persistence import LibraryDB
from infrastructure.cache.cache_keys import (
    ALBUM_INFO_PREFIX,
    LIBRARY_ALBUM_DETAILS_PREFIX,
)
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.cache.disk_cache import DiskMetadataCache
from infrastructure.validators import validate_mbid
from infrastructure.queue.priority_queue import RequestPriority
from core.exceptions import ResourceNotFoundError
from services.audiodb_image_service import AudioDBImageService
from repositories.audiodb_models import AudioDBAlbumImages

if TYPE_CHECKING:
    from infrastructure.persistence.album_release_pin_store import AlbumReleasePinStore
    from services.audiodb_browse_queue import AudioDBBrowseQueue
    from services.native.library_ownership_service import LibraryOwnershipService

logger = logging.getLogger(__name__)


class AlbumService:
    def __init__(
        self,
        library_repo: LibraryRepositoryProtocol,
        mb_repo: MusicBrainzRepositoryProtocol,
        library_db: LibraryDB,
        memory_cache: CacheInterface,
        disk_cache: DiskMetadataCache,
        preferences_service: PreferencesService,
        audiodb_image_service: AudioDBImageService | None = None,
        audiodb_browse_queue: "AudioDBBrowseQueue | None" = None,
        release_pin_store: "AlbumReleasePinStore | None" = None,
        ownership_service: "LibraryOwnershipService | None" = None,
    ):
        self._library_repo = library_repo
        self._mb_repo = mb_repo
        self._library_db = library_db
        self._cache = memory_cache
        self._disk_cache = disk_cache
        self._preferences_service = preferences_service
        self._audiodb_image_service = audiodb_image_service
        self._audiodb_browse_queue = audiodb_browse_queue
        # Per-album edition pins (CollectionManagement Feature E, D16); None in
        # constructions that predate the feature (tests) -> pure auto behaviour.
        self._release_pins = release_pin_store
        self._ownership = ownership_service
        self._album_in_flight: dict[str, asyncio.Future[AlbumInfo]] = {}

    async def _provider_album_id(self, identifier: str) -> str:
        if self._ownership is None:
            return identifier
        return await self._ownership.provider_album_id(identifier)

    async def resolve_album_identity(
        self,
        identifier: str,
        priority: RequestPriority = RequestPriority.USER_INITIATED,
    ) -> tuple[str, str | None]:
        """Return the canonical release group and an optional edition alias.

        Album links from enrichment providers can contain a MusicBrainz release MBID.
        The page supports those links, but acquisition and catalog ownership must use
        the containing release group. Keep the incoming release as edition context
        instead of placing it in a release-group field.
        """
        provider_id = validate_mbid(await self._provider_album_id(identifier), "album")
        release_group = await self._fetch_release_group(provider_id, priority=priority)
        canonical_id = str(release_group.get("id") or provider_id)
        release_mbid = (
            provider_id if canonical_id.casefold() != provider_id.casefold() else None
        )
        return canonical_id, release_mbid

    async def _get_audiodb_album_thumb(
        self,
        release_group_id: str,
        artist_name: str | None = None,
        album_name: str | None = None,
        *,
        allow_fetch: bool = False,
    ) -> str | None:
        if self._audiodb_image_service is None:
            return None
        try:
            if allow_fetch:
                images = await self._audiodb_image_service.fetch_and_cache_album_images(
                    release_group_id,
                    artist_name,
                    album_name,
                    is_monitored=False,
                )
            else:
                images = await self._audiodb_image_service.get_cached_album_images(
                    release_group_id
                )
            if images and not images.is_negative:
                return images.album_thumb_url
            if not allow_fetch and images is None and self._audiodb_browse_queue:
                settings = self._preferences_service.get_advanced_settings()
                if settings.audiodb_enabled:
                    await self._audiodb_browse_queue.enqueue(
                        "album",
                        release_group_id,
                        name=album_name,
                        artist_name=artist_name,
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to get AudioDB album thumb for %s: %s", release_group_id[:8], e
            )
        return None

    async def _apply_audiodb_album_images(
        self,
        album_info: AlbumInfo,
        release_group_mbid: str,
        artist_name: str | None,
        album_name: str | None,
        *,
        allow_fetch: bool = False,
        is_monitored: bool = False,
    ) -> AlbumInfo:
        if self._audiodb_image_service is None:
            return album_info
        try:
            images: AudioDBAlbumImages | None
            if allow_fetch:
                images = await self._audiodb_image_service.fetch_and_cache_album_images(
                    release_group_mbid,
                    artist_name,
                    album_name,
                    is_monitored=is_monitored,
                )
            else:
                images = await self._audiodb_image_service.get_cached_album_images(
                    release_group_mbid
                )
            if images is None or images.is_negative:
                if not allow_fetch and images is None and self._audiodb_browse_queue:
                    settings = self._preferences_service.get_advanced_settings()
                    if settings.audiodb_enabled:
                        await self._audiodb_browse_queue.enqueue(
                            "album",
                            release_group_mbid,
                            name=album_name,
                            artist_name=artist_name,
                        )
                return album_info
            album_info.album_thumb_url = images.album_thumb_url
            album_info.album_back_url = images.album_back_url
            album_info.album_cdart_url = images.album_cdart_url
            album_info.album_spine_url = images.album_spine_url
            album_info.album_3d_case_url = images.album_3d_case_url
            album_info.album_3d_flat_url = images.album_3d_flat_url
            album_info.album_3d_face_url = images.album_3d_face_url
            album_info.album_3d_thumb_url = images.album_3d_thumb_url
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to apply AudioDB images for album %s: %s",
                release_group_mbid[:8],
                e,
            )
        return album_info

    async def is_album_cached(self, release_group_id: str) -> bool:
        cache_key = f"{ALBUM_INFO_PREFIX}{release_group_id}"
        return await self._cache.get(cache_key) is not None

    async def _get_cached_album_info(
        self, release_group_id: str, cache_key: str
    ) -> Optional[AlbumInfo]:
        cached_info = await self._cache.get(cache_key)
        if cached_info:
            return cached_info

        disk_data = await self._disk_cache.get_album(release_group_id)
        if disk_data:
            # Legacy library payloads omit the release behind their tracklist.
            if disk_data.get("in_library") and "selected_release_mbid" not in disk_data:
                await self._disk_cache.delete_album(release_group_id)
                return None
            album_info = msgspec.convert(disk_data, AlbumInfo, strict=False)
            advanced_settings = self._preferences_service.get_advanced_settings()
            ttl = (
                advanced_settings.cache_ttl_album_library
                if album_info.in_library
                else advanced_settings.cache_ttl_album_non_library
            )
            await self._cache.set(cache_key, album_info, ttl_seconds=ttl)
            return album_info

        return None

    async def _save_album_to_cache(
        self, release_group_id: str, album_info: AlbumInfo
    ) -> None:
        cache_key = f"{ALBUM_INFO_PREFIX}{release_group_id}"
        advanced_settings = self._preferences_service.get_advanced_settings()
        ttl = (
            advanced_settings.cache_ttl_album_library
            if album_info.in_library
            else advanced_settings.cache_ttl_album_non_library
        )
        await self._cache.set(cache_key, album_info, ttl_seconds=ttl)
        await self._disk_cache.set_album(
            release_group_id,
            album_info,
            is_monitored=album_info.in_library,
            ttl_seconds=ttl if not album_info.in_library else None,
        )

    async def _current_library_membership(self, album_id: str) -> bool:
        """Membership is mutable library state, never authoritative cache metadata."""
        return (
            await self._library_db.resolve_library_album_identifier(album_id)
            is not None
        )

    async def warm_full_album_cache(self, release_group_id: str) -> None:
        release_group_id = await self._provider_album_id(release_group_id)
        try:
            cache_key = f"{ALBUM_INFO_PREFIX}{release_group_id}"
            if await self._get_cached_album_info(release_group_id, cache_key):
                return
            await self.get_album_info(
                release_group_id, priority=RequestPriority.BACKGROUND_SYNC
            )
        except Exception:  # noqa: BLE001
            pass

    async def refresh_album(self, release_group_id: str) -> AlbumInfo:
        release_group_id = await self._provider_album_id(release_group_id)
        release_group_id = validate_mbid(release_group_id, "album")

        await self._cache.delete(f"{ALBUM_INFO_PREFIX}{release_group_id}")
        await self._cache.delete(f"{LIBRARY_ALBUM_DETAILS_PREFIX}{release_group_id}")
        await self._disk_cache.delete_album(release_group_id)
        self._album_in_flight.pop(release_group_id, None)

        return await self.get_album_info(release_group_id)

    async def get_album_info(
        self,
        release_group_id: str,
        library_mbids: set[str] = None,
        priority: RequestPriority = RequestPriority.USER_INITIATED,
    ) -> AlbumInfo:
        release_group_id = await self._provider_album_id(release_group_id)
        try:
            release_group_id = validate_mbid(release_group_id, "album")
        except ValueError as e:
            logger.error(f"Invalid album MBID: {e}")
            raise
        try:
            cache_key = f"{ALBUM_INFO_PREFIX}{release_group_id}"
            cached = await self._get_cached_album_info(release_group_id, cache_key)
            if cached:
                current_in_library = await self._current_library_membership(
                    release_group_id
                )
                if cached.in_library != current_in_library:
                    cached = msgspec.structs.replace(
                        cached, in_library=current_in_library
                    )
                cached = await self._apply_audiodb_album_images(
                    cached,
                    release_group_id,
                    cached.artist_name,
                    cached.title,
                    allow_fetch=True,
                    is_monitored=cached.in_library,
                )
                return cached

            if release_group_id in self._album_in_flight:
                return await asyncio.shield(self._album_in_flight[release_group_id])

            loop = asyncio.get_running_loop()
            future: asyncio.Future[AlbumInfo] = loop.create_future()
            self._album_in_flight[release_group_id] = future
            try:
                album_info = await self._do_get_album_info(
                    release_group_id, cache_key, library_mbids, priority
                )
                if not future.done():
                    future.set_result(album_info)
                return album_info
            except BaseException as exc:
                if not future.done():
                    future.set_exception(exc)
                raise
            finally:
                self._album_in_flight.pop(release_group_id, None)
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"API call failed for album {release_group_id}: {e}")
            raise ResourceNotFoundError(f"Failed to get album info: {e}")

    async def _do_get_album_info(
        self,
        release_group_id: str,
        cache_key: str,
        library_mbids: set[str] | None,
        priority: RequestPriority,
    ) -> AlbumInfo:
        album_info = await self._build_album_from_musicbrainz(
            release_group_id, library_mbids, priority
        )
        album_info = await self._apply_audiodb_album_images(
            album_info,
            release_group_id,
            album_info.artist_name,
            album_info.title,
            allow_fetch=True,
            is_monitored=album_info.in_library,
        )
        await self._save_album_to_cache(release_group_id, album_info)
        return album_info

    async def get_album_basic_info(self, release_group_id: str) -> AlbumBasicInfo:
        release_group_id = await self._provider_album_id(release_group_id)
        try:
            release_group_id = validate_mbid(release_group_id, "album")
        except ValueError as e:
            logger.error(f"Invalid album MBID: {e}")
            raise

        try:
            cache_key = f"{ALBUM_INFO_PREFIX}{release_group_id}"

            try:
                if self._library_repo.is_configured():
                    requested_mbids = await self._library_repo.get_requested_mbids()
                else:
                    requested_mbids = set()
            except Exception:  # noqa: BLE001
                logger.warning("Lidarr unavailable, proceeding without requested data")
                requested_mbids = set()
            is_requested = release_group_id.lower() in requested_mbids

            cached_album_info = await self._get_cached_album_info(
                release_group_id, cache_key
            )
            if cached_album_info:
                in_library = await self._current_library_membership(release_group_id)
                album_thumb = cached_album_info.album_thumb_url
                if not album_thumb:
                    album_thumb = await self._get_audiodb_album_thumb(
                        release_group_id,
                        cached_album_info.artist_name,
                        cached_album_info.title,
                        allow_fetch=False,
                    )
                return AlbumBasicInfo(
                    title=cached_album_info.title,
                    musicbrainz_id=cached_album_info.musicbrainz_id,
                    artist_name=cached_album_info.artist_name,
                    artist_id=cached_album_info.artist_id,
                    release_date=cached_album_info.release_date,
                    year=cached_album_info.year,
                    type=cached_album_info.type,
                    disambiguation=cached_album_info.disambiguation,
                    in_library=in_library,
                    requested=is_requested and not in_library,
                    cover_url=cached_album_info.cover_url,
                    album_thumb_url=album_thumb,
                )

            release_group = await self._fetch_release_group(release_group_id)
            # in_library means non-deleted local files exist; the materialised
            # library_albums row lags removals and misses manually-added files.
            # Key the check on the canonical RG id - when the requested id was a
            # release-MBID alias (#78), local files live under the real one.
            canonical_rg_id = release_group.get("id") or release_group_id
            is_requested = (
                canonical_rg_id.lower() in requested_mbids
                or release_group_id.lower() in requested_mbids
            )
            in_library = await self._library_db.has_album_files(canonical_rg_id)
            basic = AlbumBasicInfo(
                **mb_to_basic_info(
                    release_group, canonical_rg_id, in_library, is_requested
                )
            )
            basic.album_thumb_url = await self._get_audiodb_album_thumb(
                canonical_rg_id,
                basic.artist_name,
                basic.title,
                allow_fetch=False,
            )
            return basic

        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to get basic album info for {release_group_id}: {e}")
            raise ResourceNotFoundError(f"Failed to get album info: {e}")

    async def get_album_tracks_info(
        self,
        release_group_id: str,
        priority: RequestPriority = RequestPriority.USER_INITIATED,
    ) -> AlbumTracksInfo:
        """``priority`` (P4): background callers - the orchestrator's completion-time
        coverage check - pass BACKGROUND_SYNC so a cold-cache finalize never jumps the
        MusicBrainz queue ahead of a user's page load (honest-priority house rule).
        Normally warm: the request flow fetched this at task creation."""
        release_group_id = await self._provider_album_id(release_group_id)
        try:
            release_group_id = validate_mbid(release_group_id, "album")
        except ValueError as e:
            logger.error(f"Invalid album MBID: {e}")
            raise

        try:
            cache_key = f"{ALBUM_INFO_PREFIX}{release_group_id}"
            cached_album_info = await self._get_cached_album_info(
                release_group_id, cache_key
            )
            if cached_album_info:
                return AlbumTracksInfo(
                    tracks=cached_album_info.tracks,
                    total_tracks=cached_album_info.total_tracks,
                    total_length=cached_album_info.total_length,
                    label=cached_album_info.label,
                    barcode=cached_album_info.barcode,
                    country=cached_album_info.country,
                    selected_release_mbid=cached_album_info.selected_release_mbid,
                )

            release_group = await self._fetch_release_group(
                release_group_id, priority=priority
            )
            ranked_releases = get_ranked_releases(release_group)

            if not ranked_releases:
                return AlbumTracksInfo(tracks=[], total_tracks=0)

            tracks: list[Track] = []
            total_length = 0
            release_data = None

            canonical_rg_id = release_group.get("id") or release_group_id
            selected_release_id, _owned, _pinned = await self._effective_release_id(
                canonical_rg_id, release_group
            )
            ranked_ids = [r.get("id") for r in ranked_releases[:3] if r.get("id")]
            candidate_ids = list(
                dict.fromkeys(rid for rid in (selected_release_id, *ranked_ids) if rid)
            )
            resolved_release_id = None
            if candidate_ids:
                release_results = await asyncio.gather(
                    *(
                        self._mb_repo.get_release_by_id(
                            rid, includes=["recordings", "labels"], priority=priority
                        )
                        for rid in candidate_ids
                    ),
                    return_exceptions=True,
                )
                failures = [r for r in release_results if isinstance(r, Exception)]
                if failures:
                    logger.warning(
                        f"Album {release_group_id[:8]}: {len(failures)}/{len(candidate_ids)} release fetches failed"
                    )
                for candidate_id, result in zip(candidate_ids, release_results):
                    if isinstance(result, Exception) or not result:
                        continue
                    found_tracks, found_length = extract_tracks(result)
                    if found_tracks:
                        tracks = found_tracks
                        total_length = found_length
                        release_data = result
                        resolved_release_id = candidate_id
                        break

            if not release_data:
                return AlbumTracksInfo(tracks=[], total_tracks=0)

            label = extract_label(release_data)

            return AlbumTracksInfo(
                tracks=tracks,
                total_tracks=len(tracks),
                total_length=total_length if total_length > 0 else None,
                label=label,
                barcode=release_data.get("barcode"),
                country=release_data.get("country"),
                selected_release_mbid=resolved_release_id,
            )

        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to get album tracks for {release_group_id}: {e}")
            raise ResourceNotFoundError(f"Failed to get album tracks: {e}")

    async def annotate_album_coverage(self, release_group_id: str, status):  # noqa: ANN001
        """Fill a ``LibraryAlbumStatus``'s coverage fields (P5, 2026-07-05 incident):
        which held files actually COVER the release's expected tracks, and which are
        orphans ("doesn't match this album"). Uses the same shared matcher as the
        download completeness gate, so the album page and the orchestrator can never
        disagree about what "In Library" means. Fail-open: any tracklist failure
        leaves the coverage fields zeroed and the page falls back to presence-only."""
        if not status.tracks:
            return status
        try:
            info = await self.get_album_tracks_info(release_group_id)
        except Exception:  # noqa: BLE001 - coverage is an annotation, never a page-breaker
            logger.warning(
                f"Album coverage annotation failed for {release_group_id[:8]}"
            )
            return status
        tracks = list(info.tracks or [])
        if not tracks:
            return status
        from services.native.coverage import match_rows_to_tracks

        rows = [
            {
                "id": t.id,
                "recording_mbid": t.recording_mbid,
                "disc_number": t.disc_number,
                "track_number": t.track_number,
                "track_title": t.track_title,
                "duration_seconds": t.duration_seconds,
            }
            for t in status.tracks
        ]
        covered, orphan_rows, matched_ids = match_rows_to_tracks(rows, tracks)
        orphan_ids = {r["id"] for r in orphan_rows if r.get("id")}
        status.expected_tracks = len(tracks)
        status.covered_tracks = covered
        status.matched_file_ids = matched_ids
        status.orphans = [t for t in status.tracks if t.id in orphan_ids]
        return status

    async def _fetch_release_group(
        self,
        release_group_id: str,
        priority: RequestPriority = RequestPriority.USER_INITIATED,
    ) -> dict:
        includes = ["artists", "releases", "media", "tags"]
        rg_result = await self._mb_repo.get_release_group_by_id(
            release_group_id,
            includes=includes,
            priority=priority,
        )

        if not rg_result:
            # Last.fm top-albums and other sources sometimes hand us a
            # *release* MBID where a release-group MBID belongs, and MusicBrainz
            # correctly 404s the RG lookup (#78). Resolve release -> release group
            # and retry before declaring the album missing.
            resolved_id = await self._mb_repo.get_release_group_id_from_release(
                release_group_id, priority=priority
            )
            if resolved_id and resolved_id != release_group_id:
                rg_result = await self._mb_repo.get_release_group_by_id(
                    resolved_id,
                    includes=includes,
                    priority=priority,
                )

        if not rg_result:
            raise ResourceNotFoundError(f"Release group {release_group_id} not found")

        return rg_result

    async def _check_in_library(
        self, release_group_id: str, library_mbids: set[str] = None
    ) -> bool:
        if library_mbids is not None:
            return release_group_id.lower() in library_mbids

        library_mbids = await self._library_repo.get_library_mbids(
            include_release_ids=True
        )
        return release_group_id.lower() in library_mbids

    def _build_basic_info(
        self,
        release_group: dict,
        release_group_id: str,
        artist_name: str,
        artist_id: str,
        in_library: bool,
    ) -> AlbumInfo:
        return AlbumInfo(
            **build_album_basic_info(
                release_group, release_group_id, artist_name, artist_id, in_library
            )
        )

    async def _library_edition_evidence(
        self, release_group_id: str
    ) -> tuple[str | None, int | None]:
        """Return stored edition and file count only when one local album is active.

        A provider group can map to preserved duplicates. Never combine active albums;
        empty historical albums contribute no rows.
        """
        rows = await self._library_db.get_library_files_for_album(release_group_id)

        if not rows:
            return None, None

        local_album_ids = {
            str(
                row.get("local_album_id")
                or row.get("release_group_mbid")
                or release_group_id
            )
            for row in rows
        }
        if len(local_album_ids) != 1:
            return None, None

        release_counts: dict[str, int] = {}
        for row in rows:
            value = row.get("provider_release_mbid") or row.get("release_mbid")
            if value:
                release_mbid = str(value)
                release_counts[release_mbid] = release_counts.get(release_mbid, 0) + 1
        owned = (
            min(release_counts, key=lambda value: (-release_counts[value], value))
            if release_counts
            else None
        )
        return owned, len(rows)

    @staticmethod
    def _closest_release_id(ranked_releases: list[dict], file_count: int) -> str | None:
        """Choose the closest known MusicBrainz media count, preserving rank on ties.

        Live-verified against MusicBrainz on 2026-07-20 with Avalon release group
        4b6276da-e7c7-36df-8771-34b92f774d3b: each release has a ``media`` array whose
        entries expose the hyphenated integer ``track-count`` field (11, 20, and 11).
        """
        counted: list[tuple[int, int, str]] = []
        for rank, release in enumerate(ranked_releases):
            release_id = release.get("id")
            if not release_id:
                continue
            try:
                track_count = sum(
                    int(medium.get("track-count") or 0)
                    for medium in (release.get("media") or [])
                )
            except (TypeError, ValueError):
                continue
            if track_count > 0:
                counted.append((abs(track_count - file_count), rank, str(release_id)))
        return min(counted)[2] if counted else None

    async def _effective_release_id(
        self, release_group_id: str, release_group: dict
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve selected, owned, and pinned release IDs.

        Precedence is a valid manual pin, explicit stored album identity, the closest
        media count for one active local album, then the existing release ranking.
        Inferred choices never become owned identification evidence.
        """
        releases = release_group.get("releases") or release_group.get(
            "release-list", []
        )
        release_ids = {str(release["id"]) for release in releases if release.get("id")}
        ranked_releases = get_ranked_releases(release_group)
        ranked_ids = [
            str(release["id"]) for release in ranked_releases if release.get("id")
        ]

        pinned = await self._pinned_release_id(release_group_id)
        owned, file_count = await self._library_edition_evidence(release_group_id)

        if pinned in release_ids:
            return pinned, owned, pinned
        if owned in release_ids:
            return owned, owned, pinned
        if file_count is not None:
            inferred = self._closest_release_id(ranked_releases, file_count)
            if inferred:
                return inferred, owned, pinned
        return (ranked_ids[0] if ranked_ids else None), owned, pinned

    async def _pinned_release_id(self, release_group_id: str) -> str | None:
        if self._release_pins is None:
            return None
        return await self._release_pins.get(release_group_id)

    async def resolve_edition(self, release_group_id: str) -> str | None:
        release_group_id = await self._provider_album_id(release_group_id)
        release_group_id = validate_mbid(release_group_id, "album")
        release_group = await self._fetch_release_group(release_group_id)
        canonical_id = str(release_group.get("id") or release_group_id)
        selected, _owned, _pinned = await self._effective_release_id(
            canonical_id, release_group
        )
        return selected

    async def list_editions(self, release_group_id: str) -> dict:
        release_group_id = await self._provider_album_id(release_group_id)
        release_group_id = validate_mbid(release_group_id, "album")
        release_group = await self._fetch_release_group(release_group_id)
        canonical_id = str(release_group.get("id") or release_group_id)
        releases = release_group.get("releases") or release_group.get(
            "release-list", []
        )
        selected, owned, pinned = await self._effective_release_id(
            canonical_id, release_group
        )
        items = []
        for rel in releases:
            rel_id = rel.get("id")
            if not rel_id:
                continue
            track_count = sum(
                int(m.get("track-count") or 0) for m in (rel.get("media") or [])
            )
            items.append(
                {
                    "release_mbid": rel_id,
                    "title": rel.get("title"),
                    "disambiguation": rel.get("disambiguation") or None,
                    "date": rel.get("date") or None,
                    "country": rel.get("country") or None,
                    "packaging": rel.get("packaging") or None,
                    "status": rel.get("status") or None,
                    "track_count": track_count,
                    "is_owned": rel_id == owned,
                    "is_pinned": rel_id == pinned,
                }
            )
        return {
            "items": items,
            "pinned_release_mbid": pinned,
            "owned_release_mbid": owned,
            "selected_release_mbid": selected,
        }

    async def _bust_album_caches(self, release_group_id: str) -> None:
        """The pin changes the served tracklist/disambiguation, so the cached album
        payloads must go (mirrors refresh_album/_build_scan_invalidation)."""
        await self._cache.delete(f"{ALBUM_INFO_PREFIX}{release_group_id}")
        await self._cache.delete(f"{LIBRARY_ALBUM_DETAILS_PREFIX}{release_group_id}")
        await self._disk_cache.delete_album(release_group_id)
        self._album_in_flight.pop(release_group_id, None)

    async def set_edition_pin(
        self, release_group_id: str, release_mbid: str, user_id: str | None
    ) -> None:
        """Pin an edition (admin/trusted; the route guards the role). Validates the
        release belongs to this group before pinning, then busts the album caches."""
        release_group_id = await self._provider_album_id(release_group_id)
        release_group_id = validate_mbid(release_group_id, "album")
        if self._release_pins is None:
            raise ResourceNotFoundError("Edition pinning is unavailable")
        editions = await self.list_editions(release_group_id)
        if not any(item["release_mbid"] == release_mbid for item in editions["items"]):
            raise ResourceNotFoundError("That edition does not belong to this album")
        await self._release_pins.set(release_group_id, release_mbid, user_id)
        await self._bust_album_caches(release_group_id)

    async def clear_edition_pin(self, release_group_id: str) -> bool:
        release_group_id = await self._provider_album_id(release_group_id)
        release_group_id = validate_mbid(release_group_id, "album")
        if self._release_pins is None:
            return False
        cleared = await self._release_pins.clear(release_group_id)
        if cleared:
            await self._bust_album_caches(release_group_id)
        return cleared

    async def _enrich_with_release_details(
        self,
        album_info: AlbumInfo,
        release_id: str,
        priority: RequestPriority = RequestPriority.USER_INITIATED,
    ) -> None:
        try:
            release_data = await self._mb_repo.get_release_by_id(
                release_id, includes=["recordings", "labels"], priority=priority
            )

            if not release_data:
                logger.warning(f"Release {release_id} not found")
                return

            tracks, total_length = extract_tracks(release_data)
            album_info.tracks = tracks
            album_info.total_tracks = len(tracks)
            album_info.total_length = total_length if total_length > 0 else None

            album_info.label = extract_label(release_data)

            album_info.barcode = release_data.get("barcode")
            album_info.country = release_data.get("country")

        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to enrich with release details: {e}")

    async def _build_album_from_musicbrainz(
        self,
        release_group_id: str,
        library_mbids: set[str] = None,
        priority: RequestPriority = RequestPriority.USER_INITIATED,
    ) -> AlbumInfo:
        release_group = await self._fetch_release_group(
            release_group_id, priority=priority
        )
        primary_release = find_primary_release(release_group)
        artist_name, artist_id = extract_artist_info(release_group)

        # in_library reflects non-deleted local files, not the library_albums row
        # (see get_album_basic_info). Keyed on the canonical RG id - when the
        # requested id was a release-MBID alias (#78), files live under the real one.
        canonical_rg_id = release_group.get("id") or release_group_id
        has_files = await self._library_db.has_album_files(canonical_rg_id)
        in_library = has_files

        if not in_library:
            in_library = await self._check_in_library(canonical_rg_id, library_mbids)

        basic_info = self._build_basic_info(
            release_group, canonical_rg_id, artist_name, artist_id, in_library
        )

        selected_release_id, _owned, _pinned = await self._effective_release_id(
            canonical_rg_id, release_group
        )
        primary_id = primary_release.get("id") if primary_release else None
        for release_id in dict.fromkeys(
            rid for rid in (selected_release_id, primary_id) if rid
        ):
            await self._enrich_with_release_details(
                basic_info, release_id, priority=priority
            )
            if basic_info.tracks:
                basic_info.selected_release_mbid = release_id
                break

        return basic_info
