import msgspec


class MbContributionArtist(msgspec.Struct):
    id: str = ""
    name: str = ""


class MbContributionArtistCredit(msgspec.Struct):
    name: str = ""
    joinphrase: str = ""
    artist: MbContributionArtist = msgspec.field(default_factory=MbContributionArtist)


class MbContributionReleaseGroup(msgspec.Struct):
    id: str = ""
    title: str = ""
    primary_type: str | None = msgspec.field(name="primary-type", default=None)
    secondary_types: list[str] = msgspec.field(
        name="secondary-types", default_factory=list
    )


class MbContributionRecording(msgspec.Struct):
    id: str = ""
    title: str = ""


class MbContributionTrack(msgspec.Struct):
    id: str = ""
    title: str = ""
    position: int = 0
    number: str = ""
    length: int | None = None
    recording: MbContributionRecording = msgspec.field(
        default_factory=MbContributionRecording
    )


class MbContributionMedium(msgspec.Struct):
    position: int = 1
    format: str | None = None
    title: str = ""
    tracks: list[MbContributionTrack] = msgspec.field(default_factory=list)


class MbContributionLabel(msgspec.Struct):
    id: str = ""
    name: str = ""


class MbContributionLabelInfo(msgspec.Struct):
    catalog_number: str = msgspec.field(name="catalog-number", default="")
    label: MbContributionLabel | None = None


class MbContributionRelease(msgspec.Struct):
    id: str = ""
    title: str = ""
    date: str = ""
    country: str = ""
    status: str = ""
    packaging: str = ""
    barcode: str = ""
    release_group: MbContributionReleaseGroup = msgspec.field(
        name="release-group", default_factory=MbContributionReleaseGroup
    )
    artist_credit: list[MbContributionArtistCredit] = msgspec.field(
        name="artist-credit", default_factory=list
    )
    media: list[MbContributionMedium] = msgspec.field(default_factory=list)
    label_info: list[MbContributionLabelInfo] = msgspec.field(
        name="label-info", default_factory=list
    )


class MbContributionRelation(msgspec.Struct):
    target_type: str = msgspec.field(name="target-type", default="")
    type: str = ""
    type_id: str = msgspec.field(name="type-id", default="")
    release: MbContributionRelease | None = None
    release_group: MbContributionReleaseGroup | None = None
    artist: MbContributionArtist | None = None
    label: MbContributionLabel | None = None


class MbContributionUrl(msgspec.Struct):
    resource: str = ""
    relations: list[MbContributionRelation] = msgspec.field(default_factory=list)


class MbContributionReleaseSearch(msgspec.Struct):
    releases: list[MbContributionRelease] = msgspec.field(default_factory=list)
