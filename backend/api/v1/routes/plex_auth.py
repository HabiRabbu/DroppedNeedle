import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from api.v1.schemas.settings import PlexOAuthPinResponse, PlexOAuthPollResponse
from core.dependencies import get_plex_repository, get_preferences_service
from core.exceptions import PlexApiError
from infrastructure.msgspec_fastapi import MsgSpecRoute
from repositories.plex_repository import PlexRepository
from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/plex", tags=["plex-auth"])


def _get_or_create_client_id(preferences: PreferencesService) -> str:
    return preferences.get_or_create_setting("plex_client_id", lambda: str(uuid.uuid4()))


@router.post("/auth/pin", response_model=PlexOAuthPinResponse)
async def create_plex_pin(
    preferences: PreferencesService = Depends(get_preferences_service),
    repo: PlexRepository = Depends(get_plex_repository),
):
    try:
        client_id = _get_or_create_client_id(preferences)
        pin = await repo.create_oauth_pin(client_id)
        auth_url = (
            f"https://app.plex.tv/auth#?clientID={client_id}"
            f"&code={pin.code}"
            f"&context%5Bdevice%5D%5Bproduct%5D=DroppedNeedle"
        )
        return PlexOAuthPinResponse(
            pin_id=pin.id,
            pin_code=pin.code,
            auth_url=auth_url,
        )
    except PlexApiError as e:
        logger.error("Failed to create Plex OAuth pin: %s", e)
        raise HTTPException(status_code=502, detail="Could not start Plex authentication")
    except Exception as e:
        logger.exception("Unexpected error creating Plex pin: %s", e)
        raise HTTPException(status_code=500, detail="Internal error during Plex authentication")


@router.get("/auth/poll", response_model=PlexOAuthPollResponse)
async def poll_plex_pin(
    pin_id: int,
    preferences: PreferencesService = Depends(get_preferences_service),
    repo: PlexRepository = Depends(get_plex_repository),
):
    try:
        client_id = _get_or_create_client_id(preferences)
        token = await repo.poll_oauth_pin(pin_id, client_id)
        if token:
            return PlexOAuthPollResponse(completed=True, auth_token=token)
        return PlexOAuthPollResponse(completed=False)
    except Exception as e:
        logger.exception("Error polling Plex pin %d: %s", pin_id, e)
        raise HTTPException(status_code=502, detail="Error polling Plex authentication status")
