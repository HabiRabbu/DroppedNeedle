"""Jellyfin error-status mapping: clients expect real HTTP codes, not the native
``{"error":...}`` envelope, so map every exception to a status (01-architecture.md s8)."""

from __future__ import annotations

from core.exceptions import (
    ConflictError,
    ExternalServiceError,
    JellyfinError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)

BAD_REQUEST = 400
UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
CONFLICT = 409
SERVER_ERROR = 500


def to_jellyfin_status(exc: Exception) -> tuple[int, dict | None]:
    # JellyfinError carries its own status/body; subclasses map via their base;
    # ExternalServiceError and anything unexpected become 500.
    if isinstance(exc, JellyfinError):
        return exc.status, exc.body
    if isinstance(exc, ResourceNotFoundError):
        return NOT_FOUND, None
    if isinstance(exc, PermissionDeniedError):
        return FORBIDDEN, None
    if isinstance(exc, ConflictError):
        return CONFLICT, None
    if isinstance(exc, ValidationError):
        return BAD_REQUEST, None
    if isinstance(exc, ExternalServiceError):
        return SERVER_ERROR, None
    return SERVER_ERROR, None
