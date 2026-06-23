"""Per-protocol enablement guards for the compat shims.

A disabled protocol must fail in a protocol-appropriate way (01 s10): Subsonic
returns a status=failed envelope (code 0); Jellyfin returns HTTP 404 on
/System/Info/Public so clients cannot connect.
"""

from __future__ import annotations

from api.v1.schemas.settings import ConnectAppsSettings
from core.exceptions import JellyfinError, SubsonicError


def is_subsonic_enabled(settings: ConnectAppsSettings) -> bool:
    return settings.subsonic_enabled


def is_jellyfin_enabled(settings: ConnectAppsSettings) -> bool:
    return settings.jellyfin_enabled


def ensure_subsonic_enabled(settings: ConnectAppsSettings) -> None:
    """Raise SubsonicError (-> status=failed envelope) when Subsonic is off."""
    if not settings.subsonic_enabled:
        raise SubsonicError(0, "The Subsonic API is disabled on this server.")


def ensure_jellyfin_enabled(settings: ConnectAppsSettings) -> None:
    """Raise JellyfinError(404) when Jellyfin is off, so clients can't connect."""
    if not settings.jellyfin_enabled:
        raise JellyfinError(404, "The Jellyfin API is disabled on this server.")
