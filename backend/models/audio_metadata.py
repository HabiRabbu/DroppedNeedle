"""Format-neutral, list-valued audio metadata read contracts."""

from __future__ import annotations

from typing import Literal

import msgspec

from models.library_management_artwork import ArtworkImageType

AudioContainer = Literal["flac", "mp3", "ogg", "opus", "m4a", "aac", "wav", "wma"]
AudioFieldValue = str | int | float | bool | tuple[str, ...]
TagValueKind = Literal["text", "integer", "boolean", "binary", "opaque"]
NativeValueKind = Literal[
    "text", "integer", "float", "boolean", "binary", "integer_pair", "opaque"
]
NativeStorageKind = Literal[
    "vorbis_comments", "id3", "mp4_atoms", "apev2", "asf_attributes"
]
AudioFieldAction = Literal["unchanged", "set", "clear", "merge", "preserve"]
AudioCleanupAction = Literal[
    "remove_id3_from_flac", "remove_apev2_from_mp3", "remove_apev2_from_aac"
]


class FormatProbe(msgspec.Struct, frozen=True, kw_only=True):
    extension: str
    admitted: bool
    detected_format: AudioContainer | None
    detected_class: str | None
    extension_matches: bool
    tag_format: str | None = None
    tag_version: str | None = None


class AudioSemanticField(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    value: AudioFieldValue


class AudioMetadataDocument(msgspec.Struct, frozen=True, kw_only=True):
    fields: tuple[AudioSemanticField, ...]
    artist_display: str | None = None
    album_artist_display: str | None = None

    def value_for(self, name: str) -> AudioFieldValue | None:
        for field in self.fields:
            if field.name == name:
                return field.value
        return None

    def strings_for(self, name: str) -> tuple[str, ...]:
        value = self.value_for(name)
        if isinstance(value, tuple):
            return value
        if isinstance(value, str):
            return (value,)
        return ()


class EmbeddedArtworkDescriptor(msgspec.Struct, frozen=True, kw_only=True):
    image_type: ArtworkImageType
    mime_type: str | None
    description: str
    width: int | None
    height: int | None
    byte_size: int
    sha256: str
    content: bytes
    format_supported: bool


class RawTagDescriptor(msgspec.Struct, frozen=True, kw_only=True):
    key: str
    values: tuple[str, ...]
    value_kind: TagValueKind
    binary_sha256: str | None = None


class NativeTagValue(msgspec.Struct, frozen=True, kw_only=True):
    kind: NativeValueKind
    text: str | None = None
    integer: int | None = None
    float_value: float | None = None
    boolean: bool | None = None
    binary: bytes | None = None
    integer_pair: tuple[int, ...] = ()
    type_code: int | None = None
    language: int | None = None
    stream: int | None = None


class NativeTagEntry(msgspec.Struct, frozen=True, kw_only=True):
    key: str
    values: tuple[NativeTagValue, ...]
    container: Literal["scalar", "list"] = "list"


class NativeMetadataSnapshot(msgspec.Struct, frozen=True, kw_only=True):
    storage_kind: NativeStorageKind
    entries: tuple[NativeTagEntry, ...] = ()
    encoded_id3: bytes | None = None
    auxiliary_storage_kind: Literal["id3", "apev2", "riff_info"] | None = None
    auxiliary_entries: tuple[NativeTagEntry, ...] = ()
    auxiliary_encoded_id3: bytes | None = None


class FileAttributeSnapshot(msgspec.Struct, frozen=True, kw_only=True):
    atime_ns: int
    mtime_ns: int
    permission_bits: int


class AudioTechnicalInfo(msgspec.Struct, frozen=True, kw_only=True):
    duration_seconds: float
    bitrate_bps: int
    sample_rate_hz: int
    channels: int
    bit_depth: int | None
    codec: str | None
    file_size_bytes: int


class ReadAudioDocument(msgspec.Struct, frozen=True, kw_only=True):
    probe: FormatProbe
    metadata: AudioMetadataDocument
    artwork: tuple[EmbeddedArtworkDescriptor, ...]
    technical: AudioTechnicalInfo
    raw_tags: tuple[RawTagDescriptor, ...]
    native_tags: NativeMetadataSnapshot
    file_attributes: FileAttributeSnapshot
    warnings: tuple[str, ...] = ()


class SemanticTagSnapshot(msgspec.Struct, frozen=True, kw_only=True):
    snapshot_version: int
    adapter_version: str
    probe: FormatProbe
    metadata: AudioMetadataDocument
    artwork: tuple[EmbeddedArtworkDescriptor, ...]
    technical: AudioTechnicalInfo
    raw_tags: tuple[RawTagDescriptor, ...]
    native_tags: NativeMetadataSnapshot
    file_attributes: FileAttributeSnapshot


class DesiredAudioField(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    action: AudioFieldAction
    value: AudioFieldValue | None = None


class DesiredCustomTag(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    action: Literal["set", "append", "delete"]
    values: tuple[str, ...] = ()


class DesiredAudioDocument(msgspec.Struct, frozen=True, kw_only=True):
    fields: tuple[DesiredAudioField, ...]
    custom_tags: tuple[DesiredCustomTag, ...] = ()
    artwork: tuple[EmbeddedArtworkDescriptor, ...] | None = None
    artist_display: str | None = None
    album_artist_display: str | None = None


class AudioWritePolicy(msgspec.Struct, frozen=True, kw_only=True):
    preserve_fields: tuple[str, ...] = ()
    scrub_unmanaged_tags: bool = False
    preserve_embedded_art_during_scrub: bool = True
    preserve_timestamps: bool = True
    preserve_permissions: bool = True
    strict_capability_gate: bool = True
    id3_version: Literal["2.4", "2.3"] = "2.4"
    id3v23_join_delimiter: str = "; "
    id3_text_encoding: Literal["utf8", "utf16"] = "utf8"
    remove_id3_from_flac: bool = False
    mp3_apev2_policy: Literal["preserve", "remove"] = "preserve"
    raw_aac_tag_policy: Literal["save_apev2", "do_not_write", "remove_apev2"] = (
        "save_apev2"
    )
    wav_tag_policy: Literal["id3", "riff_info", "preserve_existing"] = "id3"
    constrained_genres_primary_only: bool = False


class AudioFieldMutation(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    operation: AudioFieldAction
    before: AudioFieldValue | None
    after: AudioFieldValue | None
    representation_loss: str | None = None


class AudioCustomTagMutation(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    operation: Literal["set", "append", "delete", "preserve"]
    native_key: str
    before: tuple[str, ...]
    after: tuple[str, ...]


class AudioWriteCompatibility(msgspec.Struct, frozen=True, kw_only=True):
    id3_version: Literal["2.4", "2.3"] | None = None
    id3_text_encoding: Literal["utf8", "utf16"] | None = None
    id3v23_join_delimiter: str | None = None
    wav_tag_policy: Literal["id3", "riff_info", "preserve_existing"] | None = None
    raw_aac_tag_policy: Literal["save_apev2", "do_not_write", "remove_apev2"] | None = (
        None
    )


class AudioWritePlan(msgspec.Struct, frozen=True, kw_only=True):
    audio_format: AudioContainer
    adapter_name: str
    mutations: tuple[AudioFieldMutation, ...]
    custom_tag_mutations: tuple[AudioCustomTagMutation, ...]
    preserved_raw_keys: tuple[str, ...]
    scrubbed_raw_keys: tuple[str, ...]
    preserve_embedded_artwork: bool
    desired_artwork: tuple[EmbeddedArtworkDescriptor, ...]
    artist_display: str | None
    album_artist_display: str | None
    cleanup_actions: tuple[AudioCleanupAction, ...]
    compatibility: AudioWriteCompatibility
    preserve_timestamps: bool
    preserve_permissions: bool
    snapshot: SemanticTagSnapshot
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_write: bool


class AudioWriteResult(msgspec.Struct, frozen=True, kw_only=True):
    document: ReadAudioDocument
    file_sha256: str
    file_size_bytes: int
    warnings: tuple[str, ...] = ()


class FormatCapabilities(msgspec.Struct, frozen=True, kw_only=True):
    audio_format: AudioContainer
    extensions: tuple[str, ...]
    adapter_name: str
    tag_format: str
    readable: bool
    writable: bool
    native_multivalue: bool
    artwork_readable: bool
    artwork_writable: bool
    artwork_types_preserved: bool
    artwork_mime_types: tuple[str, ...]
    supported_fields: tuple[str, ...]
    unsupported_fields: tuple[str, ...]
    representation_warnings: tuple[str, ...] = ()


class CapabilityReport(msgspec.Struct, frozen=True, kw_only=True):
    probe: FormatProbe
    capabilities: FormatCapabilities | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
