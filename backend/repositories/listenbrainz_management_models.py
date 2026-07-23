"""Live-verified ListenBrainz release-group metadata wire structs."""

import msgspec


class LbManagementTag(msgspec.Struct):
    tag: str = ""
    count: int = 0
    genre_mbid: str | None = None
    artist_mbid: str | None = None


class LbManagementTagGroups(msgspec.Struct):
    artist: list[LbManagementTag] = msgspec.field(default_factory=list)
    release_group: list[LbManagementTag] = msgspec.field(
        name="release_group", default_factory=list
    )


class LbManagementReleaseGroupMetadata(msgspec.Struct):
    tag: LbManagementTagGroups = msgspec.field(default_factory=LbManagementTagGroups)
