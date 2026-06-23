from infrastructure.msgspec_fastapi import AppStruct


class FollowedArtistResponse(AppStruct):
    mbid: str
    name: str
    auto_download: bool
    auto_download_state: str
    followed_at: float
    image_url: str | None = None


class NewReleaseResponse(AppStruct):
    release_group_mbid: str
    title: str
    artist_name: str
    artist_mbid: str
    primary_type: str | None = None
    first_release_date: str | None = None


class WantedResponse(AppStruct):
    items: list[NewReleaseResponse]
    total: int
