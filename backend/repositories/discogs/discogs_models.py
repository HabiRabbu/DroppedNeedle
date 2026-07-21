from typing import Any

import msgspec


class DiscogsWireArtist(msgspec.Struct):
    id: int | None = None
    name: str = ""
    anv: str = ""
    join: str = ""
    resource_url: str = ""


class DiscogsWireLabel(msgspec.Struct):
    id: int | None = None
    name: str = ""
    catno: str = ""
    resource_url: str = ""


class DiscogsWireIdentifier(msgspec.Struct):
    type: str = ""
    value: str = ""
    description: str = ""


class DiscogsWireFormat(msgspec.Struct):
    name: str = ""
    qty: str = ""
    descriptions: list[str] = msgspec.field(default_factory=list)
    text: str = ""


class DiscogsWireTrack(msgspec.Struct):
    position: str = ""
    type_: str = "track"
    title: str = ""
    duration: str = ""
    artists: list[DiscogsWireArtist] = msgspec.field(default_factory=list)
    sub_tracks: list["DiscogsWireTrack"] = msgspec.field(default_factory=list)


class DiscogsWireRelease(msgspec.Struct):
    id: int = 0
    master_id: int | None = None
    title: str = ""
    artists_sort: str = ""
    artists: list[DiscogsWireArtist] = msgspec.field(default_factory=list)
    year: int | None = None
    country: str = ""
    released: str = ""
    labels: list[DiscogsWireLabel] = msgspec.field(default_factory=list)
    formats: list[DiscogsWireFormat] = msgspec.field(default_factory=list)
    identifiers: list[DiscogsWireIdentifier] = msgspec.field(default_factory=list)
    tracklist: list[DiscogsWireTrack] = msgspec.field(default_factory=list)
    uri: str = ""
    resource_url: str = ""


class DiscogsWireSearchFormat(msgspec.Struct):
    name: str = ""
    qty: str = ""
    descriptions: list[str] = msgspec.field(default_factory=list)


class DiscogsWireSearchResult(msgspec.Struct):
    id: int = 0
    master_id: int | None = None
    title: str = ""
    year: int | None = None
    country: str = ""
    label: list[str] = msgspec.field(default_factory=list)
    catno: str = ""
    format: list[str] = msgspec.field(default_factory=list)
    formats: list[DiscogsWireSearchFormat] = msgspec.field(default_factory=list)
    barcode: list[str] = msgspec.field(default_factory=list)
    uri: str = ""
    resource_url: str = ""


class DiscogsWireSearchResponse(msgspec.Struct):
    pagination: dict[str, Any] = msgspec.field(default_factory=dict)
    results: list[DiscogsWireSearchResult] = msgspec.field(default_factory=list)
