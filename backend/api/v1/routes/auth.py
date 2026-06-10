"""Auth routes: setup, local login/registration, sessions, admin user management."""

from __future__ import annotations

import asyncio, logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, responses, status

from api.v1.schemas.auth import (
    AuthResponse,
    CreateUserRequest,
    JellyfinLoginRequest,
    LoginRequest,
    OIDCAuthorizeResponse,
    OIDCExchangeRequest,
    PlexPinResponse,
    SessionListResponse,
    SetRoleRequest,
    SetupRequest,
    SetupStatusResponse,
    UserListResponse,
    session_to_response,
    user_to_response,
)
from core.dependencies.auth_providers import get_auth_service, get_plex_user_auth_service, get_jellyfin_user_auth_service, get_oidc_user_auth_service
from core.dependencies.cache_providers import get_preferences_service
from core.exceptions import AuthenticationError, ConfigurationError, ExternalServiceError, RegistrationError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentAdminDep, CurrentTokenDep, CurrentUserDep
from services.oidc_user_auth_service import OIDCUserAuthService
from services.auth_service import AuthService
from services.jellyfin_user_auth_service import JellyfinUserAuthService
from services.plex_user_auth_service import PlexUserAuthService

logger = logging.getLogger(__name__)

router = APIRouter(route_class = MsgSpecRoute, prefix = "/auth", tags = ["auth"])

_COOKIE_NAME = "musicseerr_session"
_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Attach an httpOnly session cookie. Marks Secure automatically when the
    request arrived over HTTPS (direct or via X-Forwarded-Proto)."""
    secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )
    response.set_cookie(
        key = _COOKIE_NAME,
        value = token,
        httponly = True,
        samesite = "lax",
        secure = secure,
        max_age = _COOKIE_MAX_AGE,
        path = "/api",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key = _COOKIE_NAME, path = "/api")


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


@router.get("/setup/status", response_model = SetupStatusResponse)
async def setup_status(auth: AuthService = Depends(get_auth_service)) -> SetupStatusResponse:
    required = await auth.is_setup_required()
    return SetupStatusResponse(required = required)


@router.get("/providers")
async def list_auth_providers(
    oidc_auth: OIDCUserAuthService = Depends(get_oidc_user_auth_service),
):
    """Return which login methods are currently configured."""
    prefs = get_preferences_service()

    jellyfin_cfg = prefs.get_jellyfin_connection()
    plex_cfg = prefs.get_plex_connection()
    oidc_cfg = oidc_auth.get_config()

    return {
        "local": True,
        "plex": plex_cfg.enabled,
        "jellyfin": jellyfin_cfg.enabled,
        "oidc": oidc_cfg.enabled and bool(oidc_cfg.issuer) and bool(oidc_cfg.client_id),
    }


@router.post("/setup", response_model = AuthResponse, status_code = status.HTTP_201_CREATED)
async def setup(
    request: Request,
    response: Response,
    body: SetupRequest = MsgSpecBody(SetupRequest),
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    if not await auth.is_setup_required():
        raise HTTPException(
            status_code = status.HTTP_409_CONFLICT,
            detail = "Setup has already been completed",
        )
    try:
        user, token = await auth.create_first_admin(
            display_name = body.display_name,
            email = body.email,
            password = body.password,
            user_agent = request.headers.get("User-Agent"),
        )
    except RegistrationError as e:
        logger.debug(f"Setup registration error: {e}")
        raise HTTPException(status_code = status.HTTP_400_BAD_REQUEST, detail = "Invalid setup data")

    _set_session_cookie(response, request, token)
    return AuthResponse(token = token, user = user_to_response(user))


@router.post("/login", response_model = AuthResponse)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest = MsgSpecBody(LoginRequest),
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        user, token = await auth.login_local(
            email = body.email,
            password = body.password,
            user_agent = request.headers.get("User-Agent"),
        )
    except AuthenticationError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid email or password",
            headers = {"WWW-Authenticate": "Bearer"},
        )

    _set_session_cookie(response, request, token)
    return AuthResponse(token = token, user = user_to_response(user))


@router.post("/logout", status_code = status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    token = _bearer_token(request) or request.cookies.get(_COOKIE_NAME)
    if token:
        await auth.logout(token)
    _clear_session_cookie(response)


@router.post("/logout-all", status_code = status.HTTP_204_NO_CONTENT)
async def logout_all(
    current_user: CurrentUserDep,
    current_token: CurrentTokenDep,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    await auth.logout_all(current_user.id, except_token_id = current_token.id)


@router.get("/me")
async def me(current_user: CurrentUserDep):
    return user_to_response(current_user)


@router.get("/sessions", response_model = SessionListResponse)
async def list_sessions(
    current_user: CurrentUserDep,
    auth: AuthService = Depends(get_auth_service),
) -> SessionListResponse:
    tokens = await auth.list_sessions(current_user.id)
    return SessionListResponse(sessions = [session_to_response(token) for token in tokens])


@router.delete("/sessions/{session_id}", status_code = status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: str,
    current_user: CurrentUserDep,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    try:
        await auth.revoke_session(session_id, requesting_user_id = current_user.id)
    except AuthenticationError as e:
        logger.debug(f"Session revocation denied for user {current_user.id[:8]}: {e}")
        raise HTTPException(status_code = status.HTTP_403_FORBIDDEN, detail = "Forbidden")


@router.get("/admin/users", response_model = UserListResponse)
async def admin_list_users(
    _admin: CurrentAdminDep,
    auth: AuthService = Depends(get_auth_service),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> UserListResponse:
    users, total = await asyncio.gather(
        auth.list_users(limit=limit, offset=offset),
        auth.count_users(),
    )
    return UserListResponse(
        users = [user_to_response(user) for user in users],
        total = total,
    )


@router.post("/admin/users", status_code = status.HTTP_201_CREATED)
async def admin_create_user(
    _admin: CurrentAdminDep,
    body: CreateUserRequest = MsgSpecBody(CreateUserRequest),
    auth: AuthService = Depends(get_auth_service),
):
    try:
        user = await auth.admin_create_user(
            display_name = body.display_name,
            email = body.email,
            password = body.password,
            role = body.role,
        )
    except RegistrationError as e:
        logger.debug(f"Admin user creation failed: {e}")
        raise HTTPException(status_code = status.HTTP_409_CONFLICT, detail = "Could not create user")
    return user_to_response(user)


@router.patch("/admin/users/{user_id}/role", status_code = status.HTTP_204_NO_CONTENT)
async def admin_set_role(
    user_id: str,
    current_admin: CurrentAdminDep,
    body: SetRoleRequest = MsgSpecBody(SetRoleRequest),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    try:
        await auth.set_role(user_id, body.role, requesting_user_id = current_admin.id)
    except AuthenticationError as e:
        logger.debug(f"Role update failed for user {user_id[:8]}: {e}")
        raise HTTPException(status_code = status.HTTP_400_BAD_REQUEST, detail = "Could not update role")


@router.delete("/admin/users/{user_id}/sessions", status_code = status.HTTP_204_NO_CONTENT)
async def admin_revoke_user_sessions(
    user_id: str,
    _admin: CurrentAdminDep,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    await auth.revoke_user_sessions(user_id)


@router.post("/plex/pin", response_model = PlexPinResponse)
async def plex_login_pin(plex_auth: PlexUserAuthService = Depends(get_plex_user_auth_service)) -> PlexPinResponse:
    pin_id, auth_url = await plex_auth.create_login_pin()
    return PlexPinResponse(pin_id = pin_id, auth_url = auth_url)


@router.get("/plex/poll")
async def plex_login_poll(
    pin_id: int,
    request: Request,
    response: Response,
    plex_auth: PlexUserAuthService = Depends(get_plex_user_auth_service),
):
    try:
        result = await plex_auth.poll_and_login(
            pin_id, user_agent = request.headers.get("User-Agent")
        )
    except AuthenticationError as e:
        logger.debug(f"Plex login rejected: {e}")
        raise HTTPException(status_code = status.HTTP_403_FORBIDDEN, detail = "Access denied")
    if result is None:
        return {"completed": False}
    user, token = result
    _set_session_cookie(response, request, token)
    return AuthResponse(token = token, user = user_to_response(user))


@router.post("/jellyfin/login", response_model = AuthResponse)
async def jellyfin_login(
    request: Request,
    response: Response,
    body: JellyfinLoginRequest = MsgSpecBody(JellyfinLoginRequest),
    jellyfin_auth: JellyfinUserAuthService = Depends(get_jellyfin_user_auth_service),
) -> AuthResponse:
    try:
        user, token = await jellyfin_auth.login(
            username = body.username,
            password = body.password,
            user_agent = request.headers.get("User-Agent"),
        )
    except AuthenticationError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid credentials",
            headers = {"WWW-Authenticate": "Bearer"},
        )
    except ExternalServiceError:
        raise HTTPException(
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE,
            detail = "Jellyfin unavailable",
        )
    _set_session_cookie(response, request, token)
    return AuthResponse(token = token, user = user_to_response(user))


@router.post("/oidc/authorize", response_model = OIDCAuthorizeResponse)
async def oidc_authorize(oidc_auth: OIDCUserAuthService = Depends(get_oidc_user_auth_service)) -> OIDCAuthorizeResponse:
    try:
        url = await oidc_auth.build_authorize_url()
    except ConfigurationError:
        raise HTTPException(status_code = status.HTTP_503_SERVICE_UNAVAILABLE, detail = "OIDC is not configured")
    return OIDCAuthorizeResponse(redirect_url = url)


@router.get("/oidc/callback")
async def oidc_callback(
    code: str,
    state: str,
    request: Request,
    oidc_auth: OIDCUserAuthService = Depends(get_oidc_user_auth_service),
):
    try:
        exchange_code = await oidc_auth.handle_callback(
            code = code,
            state = state,
            user_agent = request.headers.get("User-Agent"),
        )
    except AuthenticationError:
        raise HTTPException(status_code = status.HTTP_401_UNAUTHORIZED, detail = "OIDC authentication failed")
    except ExternalServiceError:
        raise HTTPException(status_code = status.HTTP_503_SERVICE_UNAVAILABLE, detail = "OIDC provider unavailable")
    return responses.RedirectResponse(url = f"/auth/callback?code={exchange_code}")


@router.post("/oidc/exchange", response_model = AuthResponse)
async def oidc_exchange(
    request: Request,
    response: Response,
    body: OIDCExchangeRequest = MsgSpecBody(OIDCExchangeRequest),
    oidc_auth: OIDCUserAuthService = Depends(get_oidc_user_auth_service),
) -> AuthResponse:
    try:
        user, token = await oidc_auth.exchange_code(body.code)
    except AuthenticationError:
        raise HTTPException(status_code = status.HTTP_401_UNAUTHORIZED, detail = "Invalid or expired code")
    _set_session_cookie(response, request, token)
    return AuthResponse(token = token, user = user_to_response(user))
