"""Subsonic auth resolution (02-auth-and-app-passwords.md s5.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.persistence.auth_store import UserRecord
    from services.compat.app_password_service import AppPasswordService


def _first(params: dict[str, list[str]], key: str) -> str | None:
    vals = params.get(key)
    return vals[0] if vals else None


async def resolve_subsonic_user(
    params: dict[str, list[str]], app_passwords: "AppPasswordService"
) -> "UserRecord":
    """Run the three Subsonic auth schemes; raises SubsonicError(code) on failure."""
    return await app_passwords.verify_subsonic(
        u=_first(params, "u"),
        t=_first(params, "t"),
        s=_first(params, "s"),
        p=_first(params, "p"),
        api_key=_first(params, "apiKey"),
        client=_first(params, "c"),
    )
