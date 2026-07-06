from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from api.v1.schemas.wrapped import (
    ServerWrappedResponse,
    UserWrappedResponse,
    WrappedAlbum,
    WrappedArtist,
    WrappedGenre,
    WrappedLeaderboardEntry,
    WrappedTrack,
    WrappedUserSummary,
    WrappedUsersResponse,
)
from infrastructure.persistence.auth_store import AuthStore
from services.home_charts_service import HomeChartsService
from services.per_user_client_factory import PerUserClientFactory

logger = logging.getLogger(__name__)

_TOP_N = 10
_RANGE = "this_year"


_LIST_USERS_PAGE_SIZE = 500


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def _unwrap_gather_result(result: object, label: str, user_id: str) -> list:
    """Log-and-discard helper for asyncio.gather(..., return_exceptions=True)
    results: a per-field failure shouldn't abort the whole wrapped payload,
    but silently swallowing it makes failures invisible, so log first."""
    if isinstance(result, Exception):
        logger.warning(
            f"Wrapped {label} fetch failed for user {user_id}: {result}", exc_info=result
        )
        return []
    return result if isinstance(result, list) else []


class WrappedService:
    """Aggregates per-user and server-wide ListenBrainz stats into "year in
    review" payloads for the newsletterr integration. Reuses the same
    per-user client resolution HomeChartsService relies on, plus
    HomeChartsService's existing site-wide chart methods for the server view.
    """

    def __init__(
        self,
        auth_store: AuthStore,
        client_factory: PerUserClientFactory,
        charts_service: HomeChartsService,
    ):
        self._auth_store = auth_store
        self._client_factory = client_factory
        self._charts_service = charts_service

    async def _list_all_users(self) -> list:
        """Paginates through AuthStore.list_users so instances with more than
        one page of users don't silently lose accounts off the end of a
        fixed limit."""
        all_users = []
        offset = 0
        while True:
            page = await self._auth_store.list_users(limit=_LIST_USERS_PAGE_SIZE, offset=offset)
            all_users.extend(page)
            if len(page) < _LIST_USERS_PAGE_SIZE:
                break
            offset += _LIST_USERS_PAGE_SIZE
        return all_users

    async def list_eligible_users(self) -> WrappedUsersResponse:
        users = await self._list_all_users()
        summaries = []
        for user in users:
            try:
                linked = await self._client_factory.is_listenbrainz_linked(user.id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Failed to check ListenBrainz link for user {user.id}: {e}", exc_info=e
                )
                linked = False
            summaries.append(
                WrappedUserSummary(
                    id=user.id,
                    email=user.email,
                    display_name=user.display_name,
                    has_listenbrainz=linked,
                )
            )
        return WrappedUsersResponse(year=_current_year(), users=summaries)

    async def get_user_wrapped(self, user_id: str) -> UserWrappedResponse:
        year = _current_year()
        user = await self._auth_store.get_user_by_id(user_id)
        display_name = user.display_name if user else user_id

        empty_response = UserWrappedResponse(
            user_id=user_id,
            display_name=display_name,
            year=year,
            has_data=False,
            top_artists=[],
            top_tracks=[],
            top_albums=[],
            top_genres=[],
            loved_tracks_count=0,
            total_listens_estimated=0,
        )

        try:
            lb_client = await self._client_factory.resolve_listenbrainz(user_id)
            lb_username = await self._client_factory.resolve_listenbrainz_username(user_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Failed to resolve ListenBrainz client for user {user_id}: {e}", exc_info=e
            )
            return empty_response

        if not (lb_client and lb_username):
            return empty_response

        artists, recordings, release_groups, genres, loved = await asyncio.gather(
            lb_client.get_user_top_artists(username=lb_username, range_=_RANGE, count=_TOP_N),
            lb_client.get_user_top_recordings(username=lb_username, range_=_RANGE, count=_TOP_N),
            lb_client.get_user_top_release_groups(username=lb_username, range_=_RANGE, count=_TOP_N),
            lb_client.get_user_genre_activity(username=lb_username),
            # ListenBrainz caps this endpoint at 100 results per request, so
            # loved_tracks_count below is a sample size, not a true total, see
            # WrappedTrack/UserWrappedResponse.loved_tracks_count docstring.
            lb_client.get_user_loved_recordings(username=lb_username, count=100),
            return_exceptions=True,
        )
        artists = _unwrap_gather_result(artists, "top_artists", user_id)
        recordings = _unwrap_gather_result(recordings, "top_recordings", user_id)
        release_groups = _unwrap_gather_result(release_groups, "top_release_groups", user_id)
        genres = _unwrap_gather_result(genres, "genre_activity", user_id)
        loved = _unwrap_gather_result(loved, "loved_recordings", user_id)

        top_artists = [
            WrappedArtist(
                name=a.artist_name,
                listen_count=a.listen_count,
                artist_mbid=a.artist_mbids[0] if a.artist_mbids else None,
            )
            for a in artists
        ]
        top_tracks = [
            WrappedTrack(name=r.track_name, artist_name=r.artist_name, listen_count=r.listen_count)
            for r in recordings
        ]
        top_albums = [
            WrappedAlbum(
                name=rg.release_group_name,
                artist_name=rg.artist_name,
                listen_count=rg.listen_count,
                mbid=rg.release_group_mbid,
            )
            for rg in release_groups
        ]
        top_genres = [
            WrappedGenre(genre=g.genre, listen_count=g.listen_count) for g in genres[:_TOP_N]
        ]

        return UserWrappedResponse(
            user_id=user_id,
            display_name=display_name,
            year=year,
            has_data=bool(top_artists or top_tracks or top_albums),
            top_artists=top_artists,
            top_tracks=top_tracks,
            top_albums=top_albums,
            top_genres=top_genres,
            loved_tracks_count=len(loved),
            total_listens_estimated=sum(a.listen_count for a in top_artists),
        )

    async def get_server_wrapped(self) -> ServerWrappedResponse:
        year = _current_year()
        users_resp = await self.list_eligible_users()
        eligible = [u for u in users_resp.users if u.has_listenbrainz]

        per_user_results = await asyncio.gather(
            *(self.get_user_wrapped(u.id) for u in eligible),
            return_exceptions=True,
        )
        for u, result in zip(eligible, per_user_results):
            if isinstance(result, Exception):
                logger.warning(
                    f"Failed to build wrapped stats for user {u.id}: {result}", exc_info=result
                )
        wrapped_by_user = [
            w for w in per_user_results if isinstance(w, UserWrappedResponse) and w.has_data
        ]

        leaderboard = sorted(
            (
                WrappedLeaderboardEntry(
                    display_name=w.display_name, listen_count=w.total_listens_estimated
                )
                for w in wrapped_by_user
            ),
            key=lambda entry: entry.listen_count,
            reverse=True,
        )

        top_artist_range, top_album_range = await asyncio.gather(
            self._charts_service.get_trending_artists_by_range(range_key=_RANGE, limit=1),
            self._charts_service.get_popular_albums_by_range(range_key=_RANGE, limit=1),
            return_exceptions=True,
        )

        if isinstance(top_artist_range, Exception):
            logger.warning(
                f"Failed to fetch sitewide top artist for wrapped: {top_artist_range}",
                exc_info=top_artist_range,
            )
        if isinstance(top_album_range, Exception):
            logger.warning(
                f"Failed to fetch sitewide top album for wrapped: {top_album_range}",
                exc_info=top_album_range,
            )

        top_artist_sitewide = None
        if not isinstance(top_artist_range, Exception) and top_artist_range.items:
            top = top_artist_range.items[0]
            top_artist_sitewide = WrappedArtist(
                name=top.name, listen_count=top.listen_count or 0, artist_mbid=top.mbid
            )

        top_album_sitewide = None
        if not isinstance(top_album_range, Exception) and top_album_range.items:
            top = top_album_range.items[0]
            top_album_sitewide = WrappedAlbum(
                name=top.name,
                artist_name=top.artist_name or "",
                listen_count=top.listen_count or 0,
                mbid=top.mbid,
            )

        return ServerWrappedResponse(
            year=year,
            total_users_tracked=len(wrapped_by_user),
            total_listens_estimated=sum(w.total_listens_estimated for w in wrapped_by_user),
            leaderboard=leaderboard,
            top_artist_sitewide=top_artist_sitewide,
            top_album_sitewide=top_album_sitewide,
        )
