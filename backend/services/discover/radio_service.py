"""DiscoverRadioService - generates radio sections seeded by artist, album, or genre."""

from __future__ import annotations

import logging
import random
from typing import Any, TYPE_CHECKING

from fastapi import HTTPException

from api.v1.schemas.discover import RadioRequest
from api.v1.schemas.home import HomeAlbum, HomeSection
from repositories.listenbrainz_models import ListenBrainzArtist
from repositories.protocols import (
    ListenBrainzRepositoryProtocol,
    MusicBrainzRepositoryProtocol,
)
from services.discover.integration_helpers import IntegrationHelpers
from services.discover.mbid_resolution_service import MbidResolutionService
from services.discover.queue_strategies import (
    build_similar_artist_pools,
    queue_item_to_home_album,
    round_robin_dedup_select,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DiscoverRadioService:
    def __init__(
        self,
        lb_repo: ListenBrainzRepositoryProtocol,
        mb_repo: MusicBrainzRepositoryProtocol,
        mbid_svc: MbidResolutionService,
        artist_discovery: Any = None,
        album_discovery: Any = None,
        genre_index: Any = None,
        integration: IntegrationHelpers | None = None,
        transformers: Any = None,
    ) -> None:
        self._lb_repo = lb_repo
        self._mb_repo = mb_repo
        self._mbid = mbid_svc
        self._artist_discovery = artist_discovery
        self._album_discovery = album_discovery
        self._genre_index = genre_index
        self._integration = integration
        self._transformers = transformers

    async def generate_radio(self, request: RadioRequest) -> HomeSection:
        if not request.seed_id or not request.seed_id.strip():
            raise HTTPException(status_code=400, detail="seed_id must be non-empty")

        resolved_source = (
            self._integration.resolve_source(request.source)
            if self._integration
            else request.source or "listenbrainz"
        )

        if self._integration:
            lb_enabled = self._integration.is_listenbrainz_enabled()
            lfm_enabled = self._integration.is_lastfm_enabled()
            source_available = (
                (resolved_source == "listenbrainz" and lb_enabled)
                or (resolved_source == "lastfm" and lfm_enabled)
            )
            if not source_available:
                return HomeSection(
                    title="Radio",
                    type="albums",
                    items=[],
                    source=resolved_source,
                    fallback_message=f"{resolved_source} is not enabled",
                )

        library_mbids = await self._mbid.get_library_artist_mbids(
            self._integration.is_library_configured() if self._integration else False
        )

        count = request.count or 10

        match request.seed_type:
            case "artist":
                return await self._radio_from_artist(
                    request.seed_id, library_mbids, count, resolved_source,
                )
            case "album":
                return await self._radio_from_album(
                    request.seed_id, library_mbids, count, resolved_source,
                )
            case "genre":
                return await self._radio_from_genre(
                    request.seed_id, library_mbids, count, resolved_source,
                )
            case _:
                raise ValueError(f"Unsupported seed_type: {request.seed_type}")

    async def _radio_from_artist(
        self,
        seed_id: str,
        library_mbids: set[str],
        count: int,
        source: str,
    ) -> HomeSection:
        normalized = self._mbid.normalize_mbid(seed_id)
        if not normalized:
            raise HTTPException(status_code=404, detail=f"Unknown artist MBID: {seed_id}")

        artist_name = normalized
        try:
            rgs = await self._lb_repo.get_artist_top_release_groups(normalized, count=1)
            if rgs:
                artist_name = rgs[0].artist_name or normalized
        except Exception:  # noqa: BLE001
            logger.debug("Failed to resolve artist name for %s", normalized)

        seed_stub = ListenBrainzArtist(
            artist_name=artist_name,
            artist_mbids=[normalized],
            listen_count=0,
        )

        pools = await build_similar_artist_pools(
            [seed_stub],
            excluded_mbids=library_mbids,
            similar_limit=15,
            albums_per=3,
            lb_repo=self._lb_repo,
            mbid_svc=self._mbid,
        )
        selected = round_robin_dedup_select(pools, count)
        albums = [queue_item_to_home_album(item) for item in selected]

        return HomeSection(
            title=f"Radio: {artist_name}",
            type="albums",
            items=albums,
            source=source,
            radio_seed_type="artist",
            radio_seed_id=normalized,
        )

    async def _radio_from_album(
        self,
        seed_id: str,
        library_mbids: set[str],
        count: int,
        source: str,
    ) -> HomeSection:
        normalized = self._mbid.normalize_mbid(seed_id)
        if not normalized:
            raise HTTPException(status_code=404, detail=f"Unknown album MBID: {seed_id}")

        rg_info = await self._mb_repo.get_release_group(normalized)
        if not rg_info:
            raise HTTPException(status_code=404, detail=f"Release group not found: {seed_id}")

        artist_mbid = rg_info.artist_id
        album_name = rg_info.title

        if self._album_discovery is None:
            raise ValueError("Album radio requires album_discovery service but it is not configured")

        similar_resp = await self._album_discovery.get_similar_albums(
            album_mbid=normalized, artist_mbid=artist_mbid, count=count,
        )
        more_resp = await self._album_discovery.get_more_by_artist(
            artist_mbid=artist_mbid, exclude_album_mbid=normalized, count=count,
        )

        seen: set[str] = {normalized.lower()}
        albums: list[HomeAlbum] = []

        for album in similar_resp.albums:
            mbid_lower = album.musicbrainz_id.lower()
            if mbid_lower in seen:
                continue
            seen.add(mbid_lower)
            albums.append(HomeAlbum(
                name=album.title,
                mbid=album.musicbrainz_id,
                artist_name=album.artist_name,
                artist_mbid=album.artist_id,
                image_url=f"/api/v1/covers/release-group/{album.musicbrainz_id}?size=500",
                in_library=album.in_library,
                requested=album.requested,
            ))

        for album in more_resp.albums:
            if len(albums) >= count:
                break
            mbid_lower = album.musicbrainz_id.lower()
            if mbid_lower in seen:
                continue
            seen.add(mbid_lower)
            albums.append(HomeAlbum(
                name=album.title,
                mbid=album.musicbrainz_id,
                artist_name=album.artist_name,
                artist_mbid=album.artist_id,
                image_url=f"/api/v1/covers/release-group/{album.musicbrainz_id}?size=500",
                in_library=album.in_library,
                requested=album.requested,
            ))

        return HomeSection(
            title=f"Radio: {album_name}",
            type="albums",
            items=albums[:count],
            source=source,
            radio_seed_type="album",
            radio_seed_id=normalized,
        )

    async def _radio_from_genre(
        self,
        seed_id: str,
        library_mbids: set[str],
        count: int,
        source: str,
    ) -> HomeSection:
        genre_artists = await self._genre_index.get_artists_for_genres([seed_id])
        genre_key = seed_id.strip().lower()
        artist_mbids = genre_artists.get(genre_key, [])

        if not artist_mbids:
            raise HTTPException(status_code=422, detail=f"Unknown genre tag: {seed_id}")

        sample_size = min(len(artist_mbids), 5)
        sampled = random.sample(artist_mbids, sample_size)

        seeds = [
            ListenBrainzArtist(
                artist_name=mbid,
                artist_mbids=[mbid],
                listen_count=0,
            )
            for mbid in sampled
        ]

        pools = await build_similar_artist_pools(
            seeds,
            excluded_mbids=library_mbids,
            similar_limit=10,
            albums_per=3,
            lb_repo=self._lb_repo,
            mbid_svc=self._mbid,
        )
        selected = round_robin_dedup_select(pools, count)
        albums = [queue_item_to_home_album(item) for item in selected]

        return HomeSection(
            title=f"Radio: {seed_id.title()}",
            type="albums",
            items=albums,
            source=source,
            radio_seed_type="genre",
            radio_seed_id=seed_id,
        )
