from api.v1.schemas.common import LastFmTagSchema
from models.artist import ArtistInfo as ArtistInfo
from models.artist import ExternalLink as ExternalLink
from models.artist import LifeSpan as LifeSpan
from models.artist import ReleaseItem as ReleaseItem
from infrastructure.msgspec_fastapi import AppStruct


class ArtistExtendedInfo(AppStruct):
    description: str | None = None
    image: str | None = None


class ArtistReleases(AppStruct):
    albums: list[ReleaseItem] = []
    singles: list[ReleaseItem] = []
    eps: list[ReleaseItem] = []

    offset: int = 0
    limit: int = 50
    returned_count: int = 0

    next_offset: int | None = None
    has_more: bool = False

    source_total_count: int | None = None


class LastFmSimilarArtistSchema(AppStruct):
    name: str
    mbid: str | None = None
    match: float = 0.0
    url: str | None = None


class LastFmArtistEnrichment(AppStruct):
    bio: str | None = None
    summary: str | None = None
    tags: list[LastFmTagSchema] = []
    listeners: int = 0
    playcount: int = 0
    similar_artists: list[LastFmSimilarArtistSchema] = []
    url: str | None = None


class FollowRequest(AppStruct):
    followed: bool


class AutoDownloadRequest(AppStruct):
    enabled: bool


class FollowStatusResponse(AppStruct):
    followed: bool
    auto_download: bool
    auto_download_state: str
