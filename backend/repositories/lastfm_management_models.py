"""Live-verified Last.fm wire structs for Library Management genre reads."""

import msgspec


class LastFmManagementTag(msgspec.Struct):
    name: str = ""
    url: str = ""
    count: int = 0


class LastFmManagementTopTags(msgspec.Struct):
    tags: list[LastFmManagementTag] = msgspec.field(name="tag", default_factory=list)


class LastFmManagementTopTagsResponse(msgspec.Struct):
    top_tags: LastFmManagementTopTags = msgspec.field(
        name="toptags", default_factory=LastFmManagementTopTags
    )
