"""Per-user external connection + scrobble-preference endpoints.

Endpoints are self-scoped to ``CurrentUserDep``; the encrypted ``connection_data``
ciphertext is never serialized out - only service/enabled/username.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.v1.schemas.me_connections import (
    ConnectionActionResponse,
    ConnectionsResponse,
    ConnectionStatus,
    ListenBrainzConnectRequest,
    ScrobblePreferences,
    ScrobblePreferencesUpdate,
)
from api.v1.schemas.section_prefs import (
    SectionPrefItem,
    SectionPrefsResponse,
    SectionPrefsUpdate,
)
from api.v1.schemas.settings import (
    LastFmAuthSessionRequest,
    LastFmAuthSessionResponse,
    LastFmAuthTokenResponse,
    ListenBrainzConnectionSettings,
)
from core.dependencies import (
    get_lastfm_auth_service,
    get_now_playing_service,
    get_per_user_client_factory,
    get_preferences_service,
    get_settings_service,
    get_user_connections_store,
    get_user_listening_prefs_store,
    get_user_section_prefs_store,
)
from core.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    TokenNotAuthorizedError,
)
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from infrastructure.persistence.user_connections_store import UserConnectionsStore
from infrastructure.persistence.user_listening_prefs_store import UserListeningPrefsStore
from infrastructure.persistence.user_section_prefs_store import UserSectionPrefsStore
from middleware import CurrentUserDep
from services.lastfm_auth_service import LastFmAuthService
from services.per_user_client_factory import PerUserClientFactory
from services.preferences_service import PreferencesService
from services.section_catalog import Page, sections_for, valid_keys
from services.settings_service import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/me", tags=["me"])

_SUPPORTED_SERVICES = ("lastfm", "listenbrainz")


@router.get("/connections", response_model=ConnectionsResponse)
async def list_connections(
    current_user: CurrentUserDep,
    store: UserConnectionsStore = Depends(get_user_connections_store),
) -> ConnectionsResponse:
    records = await store.list_for_user(current_user.id)
    return ConnectionsResponse(
        connections=[
            ConnectionStatus(service=r.service, enabled=r.enabled, username=r.username)
            for r in records
        ]
    )


@router.get("/scrobble-preferences", response_model=ScrobblePreferences)
async def get_scrobble_preferences(
    current_user: CurrentUserDep,
    prefs_store: UserListeningPrefsStore = Depends(get_user_listening_prefs_store),
) -> ScrobblePreferences:
    prefs = await prefs_store.get(current_user.id)
    return ScrobblePreferences(
        scrobble_to_lastfm=prefs.scrobble_to_lastfm,
        scrobble_to_listenbrainz=prefs.scrobble_to_listenbrainz,
        primary_music_source=prefs.primary_music_source,
        now_playing_visibility=prefs.now_playing_visibility,
    )


@router.put("/scrobble-preferences", response_model=ScrobblePreferences)
async def update_scrobble_preferences(
    current_user: CurrentUserDep,
    body: ScrobblePreferencesUpdate = MsgSpecBody(ScrobblePreferencesUpdate),
    prefs_store: UserListeningPrefsStore = Depends(get_user_listening_prefs_store),
    now_playing_service=Depends(get_now_playing_service),
) -> ScrobblePreferences:
    await prefs_store.upsert(
        current_user.id,
        scrobble_to_lastfm=body.scrobble_to_lastfm,
        scrobble_to_listenbrainz=body.scrobble_to_listenbrainz,
        primary_music_source=body.primary_music_source,
        now_playing_visibility=body.now_playing_visibility,
    )
    # apply the privacy change to the live presence feed immediately
    if body.now_playing_visibility is not None:
        await now_playing_service.set_visibility(
            current_user.id, body.now_playing_visibility
        )
    prefs = await prefs_store.get(current_user.id)
    return ScrobblePreferences(
        scrobble_to_lastfm=prefs.scrobble_to_lastfm,
        scrobble_to_listenbrainz=prefs.scrobble_to_listenbrainz,
        primary_music_source=prefs.primary_music_source,
        now_playing_visibility=prefs.now_playing_visibility,
    )


@router.post("/connections/lastfm/auth/token", response_model=LastFmAuthTokenResponse)
async def lastfm_request_token(
    current_user: CurrentUserDep,
    auth_service: LastFmAuthService = Depends(get_lastfm_auth_service),
    preferences_service: PreferencesService = Depends(get_preferences_service),
) -> LastFmAuthTokenResponse:
    # app api_key/shared_secret are global; only the resulting session_key is per-user
    settings = preferences_service.get_lastfm_connection()
    if not settings.api_key or not settings.shared_secret:
        raise HTTPException(status_code=400, detail="Last.fm is not configured by the administrator yet")
    try:
        token, auth_url = await auth_service.request_token(settings.api_key)
        return LastFmAuthTokenResponse(token=token, auth_url=auth_url)
    except ConfigurationError as e:
        logger.warning("Last.fm auth token request failed (config): %s", e)
        raise HTTPException(status_code=400, detail="Last.fm settings are incomplete or invalid")
    except ExternalServiceError as e:
        logger.warning("Last.fm auth token request failed (external): %s", e)
        raise HTTPException(status_code=502, detail="Couldn't reach Last.fm for a sign-in token")


@router.post("/connections/lastfm/auth/session", response_model=LastFmAuthSessionResponse)
async def lastfm_exchange_session(
    current_user: CurrentUserDep,
    request: LastFmAuthSessionRequest = MsgSpecBody(LastFmAuthSessionRequest),
    auth_service: LastFmAuthService = Depends(get_lastfm_auth_service),
    store: UserConnectionsStore = Depends(get_user_connections_store),
) -> LastFmAuthSessionResponse:
    try:
        username, session_key, _ = await auth_service.exchange_session(request.token)
        # per-user persistence, not preferences_service.save_lastfm_connection
        await store.upsert(
            current_user.id, "lastfm", {"session_key": session_key, "username": username}
        )
        return LastFmAuthSessionResponse(
            username=username, success=True, message=f"Connected as {username}"
        )
    except TokenNotAuthorizedError:
        raise HTTPException(
            status_code=502,
            detail="Last.fm access hasn't been approved yet. Authorize it, then try again.",
        )
    except ExternalServiceError as e:
        logger.warning("Last.fm session exchange failed (external): %s", e)
        raise HTTPException(status_code=502, detail="Couldn't finish the Last.fm sign-in. Please try again.")
    except ConfigurationError as e:
        logger.warning("Last.fm session exchange rejected: %s", e)
        raise HTTPException(status_code=422, detail="Last.fm configuration error. Check your settings and try again.")


@router.put("/connections/listenbrainz", response_model=ConnectionStatus)
async def connect_listenbrainz(
    current_user: CurrentUserDep,
    body: ListenBrainzConnectRequest = MsgSpecBody(ListenBrainzConnectRequest),
    settings_service: SettingsService = Depends(get_settings_service),
    store: UserConnectionsStore = Depends(get_user_connections_store),
) -> ConnectionStatus:
    # username drives every per-user ListenBrainz read; without it a "connected"
    # account yields silently-empty discovery
    if not body.username.strip():
        raise HTTPException(status_code=400, detail="A ListenBrainz username is required")
    result = await settings_service.verify_listenbrainz(
        ListenBrainzConnectionSettings(
            username=body.username, user_token=body.user_token, enabled=True
        )
    )
    if not result.valid:
        raise HTTPException(status_code=400, detail=result.message)
    await store.upsert(
        current_user.id, "listenbrainz", {"user_token": body.user_token, "username": body.username}
    )
    return ConnectionStatus(service="listenbrainz", enabled=True, username=body.username)


@router.delete("/connections/{service}", response_model=ConnectionActionResponse)
async def disconnect(
    current_user: CurrentUserDep,
    service: str,
    store: UserConnectionsStore = Depends(get_user_connections_store),
) -> ConnectionActionResponse:
    if service not in _SUPPORTED_SERVICES:
        raise HTTPException(status_code=404, detail="Unknown service")
    deleted = await store.delete(current_user.id, service)
    return ConnectionActionResponse(service=service, deleted=deleted)


async def _build_section_page(
    page: Page,
    user_id: str,
    section_prefs: UserSectionPrefsStore,
    client_factory: PerUserClientFactory,
) -> list[SectionPrefItem]:
    disabled = await section_prefs.get_disabled(user_id, page)
    lb_linked = await client_factory.is_listenbrainz_linked(user_id)
    lfm_linked = await client_factory.is_lastfm_linked(user_id)
    availability = {
        "listenbrainz": lb_linked,
        "lastfm": lfm_linked,
        # the native library engine is always present
        "library": True,
    }
    return [
        SectionPrefItem(
            key=s.key,
            title=s.title,
            description=s.description,
            zone=s.zone,
            enabled=s.key not in disabled,
            available=availability.get(s.requires, True) if s.requires else True,
            requires=s.requires,
        )
        for s in sections_for(page)
    ]


@router.get("/section-prefs", response_model=SectionPrefsResponse)
async def get_section_prefs(
    current_user: CurrentUserDep,
    section_prefs: UserSectionPrefsStore = Depends(get_user_section_prefs_store),
    client_factory: PerUserClientFactory = Depends(get_per_user_client_factory),
) -> SectionPrefsResponse:
    pages: dict[str, list[SectionPrefItem]] = {}
    for page in ("home", "discover"):
        pages[page] = await _build_section_page(
            page, current_user.id, section_prefs, client_factory
        )
    return SectionPrefsResponse(pages=pages)


@router.put("/section-prefs", response_model=SectionPrefsResponse)
async def update_section_prefs(
    current_user: CurrentUserDep,
    body: SectionPrefsUpdate = MsgSpecBody(SectionPrefsUpdate),
    section_prefs: UserSectionPrefsStore = Depends(get_user_section_prefs_store),
    client_factory: PerUserClientFactory = Depends(get_per_user_client_factory),
) -> SectionPrefsResponse:
    known = valid_keys(body.page)
    unknown = [s.key for s in body.sections if s.key not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown section keys: {', '.join(sorted(unknown))}")
    disabled = {s.key for s in body.sections if not s.enabled}
    await section_prefs.set_disabled(current_user.id, body.page, disabled)
    return SectionPrefsResponse(
        pages={
            body.page: await _build_section_page(
                body.page, current_user.id, section_prefs, client_factory
            )
        }
    )
