from infrastructure.msgspec_fastapi import AppStruct


class ExternalLink(AppStruct):
    type: str
    url: str
    label: str | list[str]
    category: str = "other"

    def __post_init__(self) -> None:
        if isinstance(self.label, list):
            object.__setattr__(self, "label", self.label[0] if self.label else self.type)


class LifeSpan(AppStruct):
    begin: str | None = None
    end: str | None = None
    ended: str | None = None


class ReleaseItem(AppStruct):
    id: str | None = None
    title: str | None = None
    type: str | None = None
    first_release_date: str | None = None
    year: int | None = None
    in_library: bool = False
    requested: bool = False


class ArtistInfo(AppStruct):
    name: str
    musicbrainz_id: str
    disambiguation: str | None = None
    type: str | None = None
    country: str | None = None
    life_span: LifeSpan | None = None
    description: str | None = None
    image: str | None = None
    fanart_url: str | None = None
    banner_url: str | None = None
    thumb_url: str | None = None
    fanart_url_2: str | None = None
    fanart_url_3: str | None = None
    fanart_url_4: str | None = None
    wide_thumb_url: str | None = None
    logo_url: str | None = None
    clearart_url: str | None = None
    cutout_url: str | None = None
    tags: list[str] = []
    aliases: list[str] = []
    external_links: list[ExternalLink] = []
    in_library: bool = False
    # Per-user follow state. The artist page reads it from the dedicated
    # /artists/{mbid}/follow endpoint, so these stay at their defaults in the
    # globally-cached struct.
    followed: bool = False
    auto_download: bool = False
    auto_download_state: str = "none"
    albums: list[ReleaseItem] = []
    singles: list[ReleaseItem] = []
    eps: list[ReleaseItem] = []
    release_group_count: int = 0
    service_status: dict[str, str] | None = None
