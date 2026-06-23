from typing import Literal

from models.common import ServiceStatus as ServiceStatus
from infrastructure.msgspec_fastapi import AppStruct


GenreArtistMap = dict[str, str | None]


class IntegrationStatus(AppStruct):
    listenbrainz: bool
    jellyfin: bool
    download_client: bool
    youtube: bool
    lastfm: bool
    navidrome: bool = False
    youtube_api: bool = False
    plex: bool = False
    library: bool = False


class StatusReport(AppStruct):
    status: Literal["ok", "degraded", "error"]
    services: dict[str, ServiceStatus]


class LastFmTagSchema(AppStruct):
    name: str
    url: str | None = None


class StatusMessageResponse(AppStruct):
    status: str
    message: str


class VerifyConnectionResponse(AppStruct):
    valid: bool
    message: str
