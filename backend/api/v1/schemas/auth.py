"""Msgspec schemas for auth endpoints."""

from __future__ import annotations

from infrastructure.msgspec_fastapi import AppStruct


class SetupStatusResponse(AppStruct):
    required: bool


class AuthProvidersResponse(AppStruct):
    local: bool
    plex: bool
    jellyfin: bool
    oidc: bool


class SetupRequest(AppStruct):
    display_name: str
    email: str
    password: str


class CreateUserRequest(AppStruct):
    display_name: str
    email: str
    password: str
    role: str = "user"


class LoginRequest(AppStruct):
    email: str
    password: str


class UserResponse(AppStruct):
    id: str
    display_name: str
    role: str
    email: str | None = None
    avatar_url: str | None = None
    providers: list[str] = []


class AuthResponse(AppStruct):
    token: str
    user: UserResponse


class SessionResponse(AppStruct):
    id: str
    issued_at: str
    expires_at: str
    last_seen_at: str
    user_agent: str | None = None


class SessionListResponse(AppStruct):
    sessions: list[SessionResponse]


class UserListResponse(AppStruct):
    users: list[UserResponse]
    total: int


class SetRoleRequest(AppStruct):
    role: str


class PlexPinResponse(AppStruct):
    pin_id: int
    auth_url: str


class PlexPollResponse(AppStruct):
    completed: bool
    token: str | None = None
    user: UserResponse | None = None


class JellyfinLoginRequest(AppStruct):
    username: str
    password: str


class OIDCAuthorizeResponse(AppStruct):
    redirect_url: str


class OIDCExchangeRequest(AppStruct):
    code: str


def user_to_response(user, providers: list[str] | None = None) -> UserResponse:
    return UserResponse(
        id = user.id,
        display_name = user.display_name,
        role = user.role,
        email = user.email,
        avatar_url = user.avatar_url,
        providers = providers or [],
    )


def session_to_response(token) -> SessionResponse:
    return SessionResponse(
        id = token.id,
        issued_at = token.issued_at,
        expires_at = token.expires_at,
        last_seen_at = token.last_seen_at,
        user_agent = token.user_agent,
    )
