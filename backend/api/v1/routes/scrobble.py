import logging

from fastapi import APIRouter, Depends, HTTPException

from api.v1.schemas.scrobble import (
    NowPlayingRequest,
    ScrobbleRequest,
    ScrobbleResponse,
)
from core.dependencies import get_scrobble_service
from core.exceptions import ConfigurationError, ExternalServiceError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentUserDep
from services.scrobble_service import ScrobbleService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/scrobble", tags=["scrobble"])


@router.post("/now-playing", response_model=ScrobbleResponse)
async def report_now_playing(
    current_user: CurrentUserDep,
    request: NowPlayingRequest = MsgSpecBody(NowPlayingRequest),
    scrobble_service: ScrobbleService = Depends(get_scrobble_service),
) -> ScrobbleResponse:
    try:
        return await scrobble_service.report_now_playing(request, user_id=current_user.id)
    except ConfigurationError as e:
        logger.warning("Scrobble now-playing config error: %s", e)
        raise HTTPException(status_code=400, detail="Scrobble not configured")
    except ExternalServiceError as e:
        logger.warning("Scrobble now-playing service error: %s", e)
        raise HTTPException(status_code=502, detail="Scrobble service unavailable")


@router.post("/submit", response_model=ScrobbleResponse)
async def submit_scrobble(
    current_user: CurrentUserDep,
    request: ScrobbleRequest = MsgSpecBody(ScrobbleRequest),
    scrobble_service: ScrobbleService = Depends(get_scrobble_service),
) -> ScrobbleResponse:
    try:
        return await scrobble_service.submit_scrobble(request, user_id=current_user.id)
    except ConfigurationError as e:
        logger.warning("Scrobble submit config error: %s", e)
        raise HTTPException(status_code=400, detail="Scrobble not configured")
    except ExternalServiceError as e:
        logger.warning("Scrobble submit service error: %s", e)
        raise HTTPException(status_code=502, detail="Scrobble service unavailable")
