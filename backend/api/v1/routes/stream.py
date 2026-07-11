import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from api.v1.schemas.stream import (
    PlaybackSessionResponse,
    ProgressReportRequest,
    StartPlaybackRequest,
    StopReportRequest,
)
from core.dependencies import (
    get_jellyfin_playback_service,
    get_local_files_service,
    get_navidrome_playback_service,
    get_plex_playback_service,
)
from core.exceptions import ExternalServiceError, PlaybackNotAllowedError, ResourceNotFoundError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentUserDep
from services.jellyfin_playback_service import JellyfinPlaybackService
from services.local_files_service import LocalFilesService
from services.navidrome_playback_service import NavidromePlaybackService
from services.plex_playback_service import PlexPlaybackService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/stream", tags=["streaming"])


@router.get("/jellyfin/{item_id}")
async def stream_jellyfin_audio(
    item_id: str,
    request: Request,
    playback_service: JellyfinPlaybackService = Depends(get_jellyfin_playback_service),
) -> StreamingResponse:
    try:
        range_header = request.headers.get("Range")
        return await playback_service.proxy_stream(item_id, range_header=range_header)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Audio item not found")
    except PlaybackNotAllowedError as e:
        logger.warning("Playback not allowed for %s: %s", item_id, e)
        raise HTTPException(status_code=403, detail="Playback not allowed")
    except ExternalServiceError as e:
        if "416" in str(e):
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        raise HTTPException(status_code=502, detail="Failed to stream from Jellyfin")


@router.head("/jellyfin/{item_id}")
async def head_jellyfin_audio(
    item_id: str,
    playback_service: JellyfinPlaybackService = Depends(get_jellyfin_playback_service),
) -> Response:
    try:
        return await playback_service.proxy_head(item_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Audio item not found")
    except PlaybackNotAllowedError as e:
        logger.warning("Playback not allowed for %s: %s", item_id, e)
        raise HTTPException(status_code=403, detail="Playback not allowed")
    except ExternalServiceError as e:
        logger.error("Jellyfin head stream error for %s: %s", item_id, e)
        raise HTTPException(status_code=502, detail="Failed to resolve Jellyfin stream")


@router.post("/jellyfin/{item_id}/start", response_model=PlaybackSessionResponse)
async def start_jellyfin_playback(
    item_id: str,
    current_user: CurrentUserDep,
    body: StartPlaybackRequest | None = Body(default=None),
    playback_service: JellyfinPlaybackService = Depends(get_jellyfin_playback_service),
) -> PlaybackSessionResponse:
    try:
        play_session_id = await playback_service.start_playback(
            item_id,
            play_session_id=body.play_session_id if body else None,
            user_id=current_user.id,
        )
        return PlaybackSessionResponse(play_session_id=play_session_id, item_id=item_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Item not found")
    except PlaybackNotAllowedError as e:
        logger.warning("Playback not allowed for %s: %s", item_id, e)
        raise HTTPException(status_code=403, detail="Playback not allowed")
    except ExternalServiceError as e:
        logger.error("Failed to start playback for %s: %s", item_id, e)
        raise HTTPException(status_code=502, detail="Failed to start Jellyfin playback")


@router.post("/jellyfin/{item_id}/progress", status_code=204)
async def report_jellyfin_progress(
    item_id: str,
    current_user: CurrentUserDep,
    body: ProgressReportRequest = MsgSpecBody(ProgressReportRequest),
    playback_service: JellyfinPlaybackService = Depends(get_jellyfin_playback_service),
) -> Response:
    try:
        await playback_service.report_progress(
            item_id=item_id,
            play_session_id=body.play_session_id,
            position_seconds=body.position_seconds,
            is_paused=body.is_paused,
            user_id=current_user.id,
        )
        return Response(status_code=204)
    except ExternalServiceError as e:
        logger.warning("Progress report failed for %s: %s", item_id, e)
        raise HTTPException(status_code=502, detail="Failed to report progress")


@router.post("/jellyfin/{item_id}/stop", status_code=204)
async def stop_jellyfin_playback(
    item_id: str,
    current_user: CurrentUserDep,
    body: StopReportRequest = MsgSpecBody(StopReportRequest),
    playback_service: JellyfinPlaybackService = Depends(get_jellyfin_playback_service),
) -> Response:
    try:
        await playback_service.stop_playback(
            item_id=item_id,
            play_session_id=body.play_session_id,
            position_seconds=body.position_seconds,
            user_id=current_user.id,
        )
        return Response(status_code=204)
    except ExternalServiceError as e:
        logger.warning("Stop report failed for %s: %s", item_id, e)
        raise HTTPException(status_code=502, detail="Failed to report playback stop")


@router.head("/local/{file_id}")
async def head_local_file(
    file_id: str,
    local_service: LocalFilesService = Depends(get_local_files_service),
) -> Response:
    try:
        headers = await local_service.head_track(file_id)
        return Response(
            status_code=200,
            headers=headers,
            media_type=headers.get("Content-Type", "application/octet-stream"),
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Track file not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Track file not found on disk")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied: path is outside the music directory")
    except ExternalServiceError as e:
        logger.error("Local head error for track %s: %s", file_id, e)
        raise HTTPException(status_code=502, detail="Failed to check local file")
    except OSError as e:
        logger.error("OS error checking local track %s: %s", file_id, e)
        raise HTTPException(status_code=500, detail="Failed to read local file")


@router.get("/local/{file_id}")
async def stream_local_file(
    file_id: str,
    request: Request,
    local_service: LocalFilesService = Depends(get_local_files_service),
) -> StreamingResponse:
    try:
        range_header = request.headers.get("Range")
        chunks, headers, status_code = await local_service.stream_track(
            file_id=file_id,
            range_header=range_header,
        )
        return StreamingResponse(
            content=chunks,
            status_code=status_code,
            headers=headers,
            media_type=headers.get("Content-Type", "application/octet-stream"),
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Track file not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Track file not found on disk")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied: path is outside the music directory")
    except ExternalServiceError as e:
        detail = str(e)
        if "Range not satisfiable" in detail:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        logger.error("Local stream error for track %s: %s", file_id, e)
        raise HTTPException(status_code=502, detail="Failed to stream local file")
    except OSError as e:
        logger.error("OS error streaming local track %s: %s", file_id, e)
        raise HTTPException(status_code=500, detail="Failed to read local file")


@router.head("/navidrome/{item_id}")
async def head_navidrome_audio(
    item_id: str,
    playback_service: NavidromePlaybackService = Depends(get_navidrome_playback_service),
) -> Response:
    try:
        return await playback_service.proxy_head(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream request")
    except ExternalServiceError:
        raise HTTPException(status_code=502, detail="Failed to stream from Navidrome")


@router.get("/navidrome/{item_id}")
async def stream_navidrome_audio(
    item_id: str,
    request: Request,
    playback_service: NavidromePlaybackService = Depends(get_navidrome_playback_service),
) -> StreamingResponse:
    try:
        return await playback_service.proxy_stream(item_id, request.headers.get("Range"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream request")
    except ExternalServiceError as e:
        detail = str(e)
        if "416" in detail or "Range not satisfiable" in detail:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        raise HTTPException(status_code=502, detail="Failed to stream from Navidrome")


@router.post("/navidrome/{item_id}/scrobble")
async def scrobble_navidrome(
    item_id: str,
    current_user: CurrentUserDep,
    playback_service: NavidromePlaybackService = Depends(get_navidrome_playback_service),
) -> dict[str, str]:
    ok = await playback_service.scrobble(item_id, user_id=current_user.id)
    return {"status": "ok" if ok else "error"}


@router.post("/navidrome/{item_id}/now-playing")
async def navidrome_now_playing(
    item_id: str,
    current_user: CurrentUserDep,
    playback_service: NavidromePlaybackService = Depends(get_navidrome_playback_service),
) -> dict[str, str]:
    ok = await playback_service.report_now_playing(item_id, user_id=current_user.id)
    return {"status": "ok" if ok else "error"}


@router.post("/navidrome/{item_id}/stopped")
async def navidrome_stopped(
    item_id: str,
    current_user: CurrentUserDep,
    playback_service: NavidromePlaybackService = Depends(get_navidrome_playback_service),
) -> dict[str, str]:
    await playback_service.clear_now_playing(item_id)
    return {"status": "ok"}


@router.head("/plex/{part_key:path}")
async def head_plex_audio(
    part_key: str,
    playback_service: PlexPlaybackService = Depends(get_plex_playback_service),
) -> Response:
    try:
        return await playback_service.proxy_head(part_key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream request")
    except ExternalServiceError:
        raise HTTPException(status_code=502, detail="Failed to stream from Plex")


@router.get("/plex/{part_key:path}")
async def stream_plex_audio(
    part_key: str,
    request: Request,
    playback_service: PlexPlaybackService = Depends(get_plex_playback_service),
) -> StreamingResponse:
    try:
        return await playback_service.proxy_stream(part_key, request.headers.get("Range"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream request")
    except ExternalServiceError as e:
        detail = str(e)
        if "416" in detail or "Range not satisfiable" in detail:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        raise HTTPException(status_code=502, detail="Failed to stream from Plex")


@router.post("/plex/{rating_key}/scrobble")
async def scrobble_plex(
    rating_key: str,
    current_user: CurrentUserDep,
    playback_service: PlexPlaybackService = Depends(get_plex_playback_service),
) -> dict[str, str]:
    ok = await playback_service.scrobble(rating_key, user_id=current_user.id)
    return {"status": "ok" if ok else "error"}


@router.post("/plex/{rating_key}/now-playing")
async def plex_now_playing(
    rating_key: str,
    current_user: CurrentUserDep,
    playback_service: PlexPlaybackService = Depends(get_plex_playback_service),
) -> dict[str, str]:
    ok = await playback_service.report_now_playing(rating_key, user_id=current_user.id)
    return {"status": "ok" if ok else "error"}


@router.post("/plex/{rating_key}/stopped")
async def plex_stopped(
    rating_key: str,
    current_user: CurrentUserDep,
    playback_service: PlexPlaybackService = Depends(get_plex_playback_service),
) -> dict[str, str]:
    ok = await playback_service.report_stopped(rating_key, user_id=current_user.id)
    return {"status": "ok" if ok else "error"}
