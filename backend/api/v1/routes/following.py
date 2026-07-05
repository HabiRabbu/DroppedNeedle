import asyncio

import msgspec
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from api.v1.schemas.following import (
    FollowedArtistResponse,
    NewReleaseResponse,
    UnseenCountResponse,
    WantedResponse,
)
from core.dependencies import get_follow_service, get_sse_publisher
from core.dependencies.type_aliases import CurrentUserDep
from infrastructure.msgspec_fastapi import MsgSpecRoute
from services.follow_service import FollowService

router = APIRouter(route_class=MsgSpecRoute, prefix="/following", tags=["following"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/events")
async def stream_following_events(
    current_user: CurrentUserDep,
    publisher=Depends(get_sse_publisher),
):
    """Per-user event stream for auto_download_enqueued. Frontend de-dupes by
    task id, so the snapshot replayed on (re)connect toasts at most once."""
    user_id = current_user.id

    async def event_generator():
        try:
            async for message in publisher.subscribe(f"user:{user_id}"):
                if not message["event"]:
                    yield ": keepalive\n\n"
                    continue
                payload = msgspec.json.encode(message["data"]).decode("utf-8")
                yield f"event: {message['event']}\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@router.get("/artists", response_model=list[FollowedArtistResponse])
async def list_followed_artists(
    current_user: CurrentUserDep,
    follow_service: FollowService = Depends(get_follow_service),
):
    artists = await follow_service.list_following(current_user.id, current_user.role)
    return [
        FollowedArtistResponse(
            mbid=a.artist_mbid,
            name=a.artist_name,
            auto_download=a.auto_download,
            auto_download_state=a.auto_download_state,
            followed_at=a.followed_at,
        )
        for a in artists
    ]


@router.get("/new-releases", response_model=WantedResponse)
async def list_new_releases(
    current_user: CurrentUserDep,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    follow_service: FollowService = Depends(get_follow_service),
):
    items, total = await follow_service.list_new_releases(current_user.id, limit, offset)
    return WantedResponse(
        items=[
            NewReleaseResponse(
                release_group_mbid=item.release_group_mbid,
                title=item.title,
                artist_name=item.artist_name,
                artist_mbid=item.artist_mbid,
                primary_type=item.primary_type,
                first_release_date=item.first_release_date,
            )
            for item in items
        ],
        total=total,
    )


@router.get("/new-releases/unseen-count", response_model=UnseenCountResponse)
async def get_unseen_new_release_count(
    current_user: CurrentUserDep,
    follow_service: FollowService = Depends(get_follow_service),
):
    count = await follow_service.count_unseen_new_releases(current_user.id)
    return UnseenCountResponse(count=count)


@router.post("/new-releases/seen", response_model=UnseenCountResponse)
async def mark_new_releases_seen(
    current_user: CurrentUserDep,
    follow_service: FollowService = Depends(get_follow_service),
):
    """Stamp the user's seen marker; the unseen count is 0 by definition after."""
    await follow_service.mark_new_releases_seen(current_user.id)
    return UnseenCountResponse(count=0)
