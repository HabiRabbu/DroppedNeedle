"""Request/response wrappers for the Connect Apps management API.

AppPasswordView is imported from app_password_service and never carries a secret.
"""

from __future__ import annotations

from infrastructure.msgspec_fastapi import AppStruct
from services.compat.app_password_service import AppPasswordView


class AppPasswordListResponse(AppStruct):
    cap: int                                  # UI renders 'X/cap'
    active_count: int
    items: list[AppPasswordView] = []


class AppPasswordCreateRequest(AppStruct):
    name: str


class AppPasswordCreateResponse(AppStruct):
    secret: str                               # plaintext app-password, shown once
    app_password: AppPasswordView
