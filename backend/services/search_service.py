import asyncio
import logging
import re
import time
import unicodedata
from math import ceil
from typing import Optional, TYPE_CHECKING
from api.v1.schemas.search import (
    SearchResult,
    SearchResponse,
    SuggestResult,
    SuggestResponse,
)
from repositories.protocols import (
    MusicBrainzRepositoryProtocol,
    LibraryRepositoryProtocol,
    CoverArtRepositoryProtocol,
)
from services.preferences_service import PreferencesService
from infrastructure.http.deduplication import deduplicate

if TYPE_CHECKING:
    from services.audiodb_image_service import AudioDBImageService
    from services.audiodb_browse_queue import AudioDBBrowseQueue
    from services.native.library_ownership_service import LibraryOwnershipService

logger = logging.getLogger(__name__)

COVER_PREFETCH_LIMIT = 12
SEARCH_CACHE_TTL = 90
SEARCH_CACHE_MAX_SIZE = 200
TOP_RESULT_SCORE_THRESHOLD = 90


class SearchService:
    _search_cache: dict[str, tuple[float, SearchResponse]] = {}

    @classmethod
    def clear_cached_results(cls) -> None:
        cls._search_cache.clear()

    def __init__(
        self,
        mb_repo: MusicBrainzRepositoryProtocol,
        library_repo: LibraryRepositoryProtocol,
        coverart_repo: CoverArtRepositoryProtocol,
        preferences_service: PreferencesService,
        audiodb_image_service: "AudioDBImageService | None" = None,
        audiodb_browse_queue: "AudioDBBrowseQueue | None" = None,
        ownership_service: "LibraryOwnershipService | None" = None,
    ):
        self._mb_repo = mb_repo
        self._library_repo = library_repo
        self._coverart_repo = coverart_repo
        self._preferences_service = preferences_service
        self._audiodb_image_service = audiodb_image_service
        self._audiodb_browse_queue = audiodb_browse_queue
        self._ownership = ownership_service

    async def _apply_album_ownership(
        self, albums: list[SearchResult], library_mbids: set[str]
    ) -> None:
        if self._ownership is None:
            for item in albums:
                item.in_library = (item.musicbrainz_id or "").lower() in library_mbids
                item.requested = False
            return
        from services.native.library_ownership_service import AlbumOwnershipCandidate

        projections = await self._ownership.project_albums(
            [
                AlbumOwnershipCandidate(
                    release_group_mbid=item.musicbrainz_id,
                    title=item.title,
                    album_artist=item.artist or "",
                    year=item.year,
                )
                for item in albums
            ]
        )
        for item, projection in zip(albums, projections):
            item.in_library = projection.owned
            item.requested = False

    async def _safe_gather(self, *tasks):
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r if not isinstance(r, Exception) else None for r in results]

    @staticmethod
    def _normalize_tokens(text: str) -> set[str]:
        """Strip diacritics and non-alphanumeric chars, then tokenize."""
        nfkd = unicodedata.normalize("NFKD", text.lower())
        stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
        cleaned = re.sub(r"[^a-z0-9\s]", "", stripped)
        return set(cleaned.split())

    @staticmethod
    def _tokens_match(query_tokens: set[str], title_tokens: set[str]) -> bool:
        """Check token overlap allowing prefix matching for partial queries."""
        min_prefix = 2
        if all(
            any(
                qt == tt or (len(qt) >= min_prefix and tt.startswith(qt))
                for tt in title_tokens
            )
            for qt in query_tokens
        ):
            return True
        if all(
            any(
                tt == qt or (len(tt) >= min_prefix and qt.startswith(tt))
                for qt in query_tokens
            )
            for tt in title_tokens
        ):
            return True
        return False

    @staticmethod
    def _detect_top_result(
        results: list[SearchResult], query: str
    ) -> SearchResult | None:
        if not results:
            return None
        best = results[0]
        if best.score < TOP_RESULT_SCORE_THRESHOLD:
            return None
        query_tokens = SearchService._normalize_tokens(query)
        title_tokens = SearchService._normalize_tokens(best.title)
        if not query_tokens or not title_tokens:
            return None
        if SearchService._tokens_match(query_tokens, title_tokens):
            return best
        return None

    async def _apply_audiodb_search_overlay(self, results: list[SearchResult]) -> None:
        if self._audiodb_image_service is None:
            return

        tasks = []
        task_indices = []
        for i, item in enumerate(results):
            if not item.musicbrainz_id:
                continue
            if item.type == "artist":
                tasks.append(
                    self._audiodb_image_service.get_cached_artist_images(
                        item.musicbrainz_id
                    )
                )
                task_indices.append(i)
            elif item.type == "album":
                tasks.append(
                    self._audiodb_image_service.get_cached_album_images(
                        item.musicbrainz_id
                    )
                )
                task_indices.append(i)

        if not tasks:
            return

        images_results = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, images in zip(task_indices, images_results):
            item = results[idx]
            if isinstance(images, Exception):
                logger.warning(
                    "AudioDB search overlay failed for %s %s: %s",
                    item.type,
                    item.musicbrainz_id[:8],
                    images,
                )
                continue
            try:
                if item.type == "artist":
                    if images and not images.is_negative:
                        if not item.thumb_url and images.thumb_url:
                            item.thumb_url = images.thumb_url
                        if not item.fanart_url and images.fanart_url:
                            item.fanart_url = images.fanart_url
                        if not item.banner_url and images.banner_url:
                            item.banner_url = images.banner_url
                    elif images is None and self._audiodb_browse_queue:
                        settings = self._preferences_service.get_advanced_settings()
                        if settings.audiodb_enabled:
                            await self._audiodb_browse_queue.enqueue(
                                "artist",
                                item.musicbrainz_id,
                                name=item.title,
                            )
                elif item.type == "album":
                    if images and not images.is_negative:
                        if not item.album_thumb_url and images.album_thumb_url:
                            item.album_thumb_url = images.album_thumb_url
                    elif images is None and self._audiodb_browse_queue:
                        settings = self._preferences_service.get_advanced_settings()
                        if settings.audiodb_enabled:
                            await self._audiodb_browse_queue.enqueue(
                                "album",
                                item.musicbrainz_id,
                                name=item.title,
                                artist_name=item.artist,
                            )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "AudioDB search overlay apply failed for %s %s: %s",
                    item.type,
                    item.musicbrainz_id[:8],
                    e,
                )

    @deduplicate(
        lambda self,
        query,
        limit_artists=10,
        limit_albums=10,
        buckets=None: f"search:{query}:{limit_artists}:{limit_albums}:{buckets}"
    )
    async def search(
        self,
        query: str,
        limit_artists: int = 10,
        limit_albums: int = 10,
        buckets: Optional[list[str]] = None,
    ) -> SearchResponse:
        cache_key = f"{query.strip().lower()}:{limit_artists}:{limit_albums}:{','.join(sorted(buckets)) if buckets else ''}"
        now = time.monotonic()
        cached = self._search_cache.get(cache_key)
        if cached and (now - cached[0]) < SEARCH_CACHE_TTL:
            return cached[1]

        prefs = self._preferences_service.get_preferences()
        included_secondary_types = set(t.lower() for t in prefs.secondary_types)
        included_primary_types = set(t.lower() for t in prefs.primary_types)

        limits = {}
        if not buckets or "artists" in buckets:
            limits["artists"] = limit_artists
        if not buckets or "albums" in buckets:
            limits["albums"] = limit_albums

        try:
            grouped, library_mbids_raw = await self._safe_gather(
                self._mb_repo.search_grouped(
                    query,
                    limits=limits,
                    buckets=buckets,
                    included_secondary_types=included_secondary_types,
                    included_primary_types=included_primary_types,
                ),
                self._library_repo.get_library_mbids(include_release_ids=True),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Search gather failed unexpectedly: {e}")
            grouped, library_mbids_raw = None, None

        if grouped is None:
            logger.warning("MusicBrainz search returned no results or failed")
        grouped = grouped or {"artists": [], "albums": []}
        library_mbids = library_mbids_raw or set()

        await self._apply_album_ownership(grouped.get("albums", []), library_mbids)

        all_results = grouped.get("artists", []) + grouped.get("albums", [])
        await self._apply_audiodb_search_overlay(all_results)

        top_artist = self._detect_top_result(grouped.get("artists", []), query)
        top_album = self._detect_top_result(grouped.get("albums", []), query)

        response = SearchResponse(
            artists=grouped.get("artists", []),
            albums=grouped.get("albums", []),
            top_artist=top_artist,
            top_album=top_album,
        )
        self._search_cache[cache_key] = (now, response)
        if len(self._search_cache) > SEARCH_CACHE_MAX_SIZE:
            expired = [
                k
                for k, (ts, _) in self._search_cache.items()
                if (now - ts) >= SEARCH_CACHE_TTL
            ]
            for k in expired:
                del self._search_cache[k]
            if len(self._search_cache) > SEARCH_CACHE_MAX_SIZE:
                oldest_key = min(
                    self._search_cache, key=lambda k: self._search_cache[k][0]
                )
                del self._search_cache[oldest_key]
        return response

    def schedule_cover_prefetch(self, albums: list[SearchResult]) -> list[str]:
        return [
            item.musicbrainz_id
            for item in albums[:COVER_PREFETCH_LIMIT]
            if item.musicbrainz_id
        ]

    @deduplicate(
        lambda self,
        bucket,
        query,
        limit=50,
        offset=0: f"search_bucket:{bucket}:{query}:{limit}:{offset}"
    )
    async def search_bucket(
        self, bucket: str, query: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[SearchResult], SearchResult | None]:
        prefs = self._preferences_service.get_preferences()
        included_secondary_types = set(t.lower() for t in prefs.secondary_types)
        included_primary_types = set(t.lower() for t in prefs.primary_types)

        if bucket == "artists":
            results = await self._mb_repo.search_artists(
                query, limit=limit, offset=offset
            )
        elif bucket == "albums":
            results = await self._mb_repo.search_albums(
                query,
                limit=limit,
                offset=offset,
                included_secondary_types=included_secondary_types,
                included_primary_types=included_primary_types,
            )
        else:
            return [], None

        if bucket == "albums":
            [library_mbids_raw] = await self._safe_gather(
                self._library_repo.get_library_mbids(include_release_ids=True),
            )
            library_mbids = library_mbids_raw or set()

            await self._apply_album_ownership(results, library_mbids)

        await self._apply_audiodb_search_overlay(results)

        top_result = self._detect_top_result(results, query) if offset == 0 else None
        return results, top_result

    @deduplicate(
        lambda self, query, limit=5: f"suggest:{query.strip().lower()}:{limit}"
    )
    async def suggest(self, query: str, limit: int = 5) -> SuggestResponse:
        query = query.strip()
        if len(query) < 2:
            return SuggestResponse()

        prefs = self._preferences_service.get_preferences()
        included_secondary_types = set(t.lower() for t in prefs.secondary_types)
        included_primary_types = set(t.lower() for t in prefs.primary_types)
        bucket_limit = ceil(limit * 0.6)

        try:
            grouped = await self._mb_repo.search_grouped(
                query,
                limits={"artists": bucket_limit, "albums": bucket_limit},
                included_secondary_types=included_secondary_types,
                included_primary_types=included_primary_types,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "MusicBrainz suggest failed (query_len=%d): %s",
                len(query),
                type(e).__name__,
            )
            return SuggestResponse()

        grouped = grouped or {"artists": [], "albums": []}

        [library_mbids_raw] = await self._safe_gather(
            self._library_repo.get_library_mbids(include_release_ids=True),
        )
        library_mbids = library_mbids_raw or set()

        await self._apply_album_ownership(grouped.get("albums", []), library_mbids)

        suggestions: list[SuggestResult] = []
        for item in grouped.get("artists", []) + grouped.get("albums", []):
            suggestions.append(
                SuggestResult(
                    type=item.type,
                    title=item.title,
                    artist=item.artist,
                    year=item.year,
                    musicbrainz_id=item.musicbrainz_id,
                    in_library=item.in_library,
                    requested=item.requested,
                    disambiguation=item.disambiguation,
                    score=item.score,
                )
            )

        type_order = {"artist": 0, "album": 1}
        suggestions.sort(
            key=lambda s: (-s.score, type_order.get(s.type, 2), s.title.lower())
        )
        return SuggestResponse(results=suggestions[:limit])
