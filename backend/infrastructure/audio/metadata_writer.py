"""Format-explicit mutation of destination-side staged audio copies."""

from __future__ import annotations

import base64
from io import BytesIO
import hashlib
import os
from pathlib import Path
import struct
import uuid

from mutagen import MutagenError
from mutagen.aac import AAC
from mutagen.apev2 import (
    APEBinaryValue,
    APEExtValue,
    APETextValue,
    APEv2,
    delete as delete_apev2,
    error as APEError,
)
from mutagen.asf import (
    ASF,
    ASFBoolAttribute,
    ASFByteArrayAttribute,
    ASFDWordAttribute,
    ASFGUIDAttribute,
    ASFQWordAttribute,
    ASFUnicodeAttribute,
    ASFWordAttribute,
)
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    MVIN,
    MVNM,
    TALB,
    TCMP,
    TCOM,
    TCON,
    TDRC,
    TDOR,
    TEXT,
    TIPL,
    TIT2,
    TMCL,
    TMED,
    TPE1,
    TPE2,
    TPE3,
    TPE4,
    TPOS,
    TPUB,
    TRCK,
    TSO2,
    TSOA,
    TSOP,
    TSOT,
    TSRC,
    TSST,
    SYLT,
    TXXX,
    UFID,
    USLT,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import AtomDataType, MP4, MP4Cover, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from core.exceptions import (
    AudioFormatMismatchError,
    AudioWriteError,
    UnsupportedAudioFormatError,
)
from infrastructure.audio.lyrics import parse_lrc
from infrastructure.audio.riff_info import read_riff_info, write_riff_info
from models.audio_metadata import (
    AudioContainer,
    AudioFieldValue,
    AudioWritePlan,
    AudioWriteResult,
    EmbeddedArtworkDescriptor,
    NativeMetadataSnapshot,
    NativeTagEntry,
    NativeTagValue,
    ReadAudioDocument,
    SemanticTagSnapshot,
)

_MB_UFID_OWNER = "http://musicbrainz.org"
_MP4_PREFIX = "----:com.apple.iTunes:"

_VORBIS_TEXT_KEYS: dict[str, tuple[str, ...]] = {
    "album": ("ALBUM",),
    "title": ("TITLE",),
    "album_sort": ("ALBUMSORT",),
    "title_sort": ("TITLESORT",),
    "artist_sort": ("ARTISTSORT",),
    "album_artist_sort": ("ALBUMARTISTSORT",),
    "disc_subtitle": ("DISCSUBTITLE",),
    "date": ("DATE",),
    "original_date": ("ORIGINALDATE",),
    "release_status": ("RELEASESTATUS", "MUSICBRAINZ_ALBUMSTATUS"),
    "release_country": ("RELEASECOUNTRY",),
    "release_type": ("RELEASETYPE", "MUSICBRAINZ_ALBUMTYPE"),
    "media": ("MEDIA",),
    "label": ("LABEL",),
    "catalog_number": ("CATALOGNUMBER",),
    "barcode": ("BARCODE",),
    "asin": ("ASIN",),
    "isrc": ("ISRC",),
    "musicbrainz_recording_id": ("MUSICBRAINZ_TRACKID",),
    "musicbrainz_release_track_id": ("MUSICBRAINZ_RELEASETRACKID",),
    "musicbrainz_release_id": ("MUSICBRAINZ_ALBUMID",),
    "musicbrainz_release_group_id": ("MUSICBRAINZ_RELEASEGROUPID",),
    "musicbrainz_artist_id": ("MUSICBRAINZ_ARTISTID",),
    "musicbrainz_album_artist_id": ("MUSICBRAINZ_ALBUMARTISTID",),
    "work": ("WORK",),
    "musicbrainz_work_id": ("MUSICBRAINZ_WORKID",),
    "movement": ("MOVEMENTNAME",),
    "composer": ("COMPOSER",),
    "lyricist": ("LYRICIST",),
    "conductor": ("CONDUCTOR",),
    "performer": ("PERFORMER",),
    "arranger": ("ARRANGER",),
    "remixer": ("REMIXER",),
    "producer": ("PRODUCER",),
    "acoustid_id": ("ACOUSTID_ID",),
    "acoustid_fingerprint": ("ACOUSTID_FINGERPRINT",),
    "genre": ("GENRE",),
    "lyrics_plain": ("LYRICS",),
    "replaygain_track_gain": ("REPLAYGAIN_TRACK_GAIN",),
    "replaygain_album_gain": ("REPLAYGAIN_ALBUM_GAIN",),
    "replaygain_track_peak": ("REPLAYGAIN_TRACK_PEAK",),
    "replaygain_album_peak": ("REPLAYGAIN_ALBUM_PEAK",),
}

_APE_TEXT_KEYS = {
    **_VORBIS_TEXT_KEYS,
    "album": ("Album",),
    "title": ("Title",),
    "artist_sort": ("ARTISTSORT",),
    "album_artist_sort": ("ALBUMARTISTSORT",),
    "disc_subtitle": ("DiscSubtitle",),
    "release_status": ("MUSICBRAINZ_ALBUMSTATUS",),
    "release_type": ("MUSICBRAINZ_ALBUMTYPE",),
    "media": ("Media",),
    "label": ("Label",),
    "catalog_number": ("CatalogNumber",),
    "barcode": ("Barcode",),
    "composer": ("Composer",),
    "lyricist": ("Lyricist",),
    "conductor": ("Conductor",),
    "performer": ("Performer",),
    "arranger": ("Arranger",),
    "remixer": ("MixArtist",),
    "producer": ("Producer",),
    "genre": ("Genre",),
    "lyrics_plain": ("Lyrics",),
}

_MP4_TEXT_KEYS: dict[str, tuple[str, ...]] = {
    "album": ("©alb",),
    "title": ("©nam",),
    "album_sort": ("soal",),
    "title_sort": ("sonm",),
    "artist_sort": ("soar",),
    "album_artist_sort": ("soaa",),
    "disc_subtitle": (f"{_MP4_PREFIX}DISCSUBTITLE",),
    "date": ("©day",),
    "original_date": (f"{_MP4_PREFIX}ORIGINALDATE",),
    "release_status": (f"{_MP4_PREFIX}MusicBrainz Album Status",),
    "release_country": (f"{_MP4_PREFIX}MusicBrainz Album Release Country",),
    "release_type": (f"{_MP4_PREFIX}MusicBrainz Album Type",),
    "media": (f"{_MP4_PREFIX}MEDIA",),
    "label": (f"{_MP4_PREFIX}LABEL",),
    "catalog_number": (f"{_MP4_PREFIX}CATALOGNUMBER",),
    "barcode": (f"{_MP4_PREFIX}BARCODE",),
    "asin": (f"{_MP4_PREFIX}ASIN",),
    "isrc": (f"{_MP4_PREFIX}ISRC",),
    "musicbrainz_recording_id": (f"{_MP4_PREFIX}MusicBrainz Track Id",),
    "musicbrainz_release_track_id": (f"{_MP4_PREFIX}MusicBrainz Release Track Id",),
    "musicbrainz_release_id": (f"{_MP4_PREFIX}MusicBrainz Album Id",),
    "musicbrainz_release_group_id": (f"{_MP4_PREFIX}MusicBrainz Release Group Id",),
    "musicbrainz_artist_id": (f"{_MP4_PREFIX}MusicBrainz Artist Id",),
    "musicbrainz_album_artist_id": (f"{_MP4_PREFIX}MusicBrainz Album Artist Id",),
    "work": ("©wrk",),
    "musicbrainz_work_id": (f"{_MP4_PREFIX}MusicBrainz Work Id",),
    "movement": ("©mvn",),
    "composer": ("©wrt",),
    "lyricist": (f"{_MP4_PREFIX}LYRICIST",),
    "conductor": (f"{_MP4_PREFIX}CONDUCTOR",),
    "remixer": (f"{_MP4_PREFIX}REMIXER",),
    "producer": (f"{_MP4_PREFIX}PRODUCER",),
    "acoustid_id": (f"{_MP4_PREFIX}Acoustid Id",),
    "acoustid_fingerprint": (f"{_MP4_PREFIX}Acoustid Fingerprint",),
    "genre": ("©gen",),
    "lyrics_plain": ("©lyr",),
    "replaygain_track_gain": (f"{_MP4_PREFIX}REPLAYGAIN_TRACK_GAIN",),
    "replaygain_album_gain": (f"{_MP4_PREFIX}REPLAYGAIN_ALBUM_GAIN",),
    "replaygain_track_peak": (f"{_MP4_PREFIX}REPLAYGAIN_TRACK_PEAK",),
    "replaygain_album_peak": (f"{_MP4_PREFIX}REPLAYGAIN_ALBUM_PEAK",),
}

_ASF_TEXT_KEYS: dict[str, tuple[str, ...]] = {
    "album": ("WM/AlbumTitle",),
    "title": ("Title",),
    "album_sort": ("WM/AlbumSortOrder",),
    "title_sort": ("WM/TitleSortOrder",),
    "artist_sort": ("WM/ArtistSortOrder",),
    "album_artist_sort": ("WM/AlbumArtistSortOrder",),
    "disc_subtitle": ("WM/SetSubTitle",),
    "date": ("WM/Year",),
    "original_date": ("WM/OriginalReleaseYear",),
    "release_status": ("MusicBrainz/Album Status",),
    "release_country": ("MusicBrainz/Album Release Country",),
    "release_type": ("MusicBrainz/Album Type",),
    "media": ("WM/Media",),
    "label": ("WM/Publisher",),
    "catalog_number": ("WM/CatalogNo",),
    "barcode": ("WM/Barcode",),
    "asin": ("ASIN",),
    "isrc": ("WM/ISRC",),
    "musicbrainz_recording_id": ("MusicBrainz/Track Id",),
    "musicbrainz_release_track_id": ("MusicBrainz/Release Track Id",),
    "musicbrainz_release_id": ("MusicBrainz/Album Id",),
    "musicbrainz_release_group_id": ("MusicBrainz/Release Group Id",),
    "musicbrainz_artist_id": ("MusicBrainz/Artist Id",),
    "musicbrainz_album_artist_id": ("MusicBrainz/Album Artist Id",),
    "work": ("WM/Work",),
    "musicbrainz_work_id": ("MusicBrainz/Work Id",),
    "composer": ("WM/Composer",),
    "lyricist": ("WM/Writer",),
    "conductor": ("WM/Conductor",),
    "remixer": ("WM/ModifiedBy",),
    "producer": ("WM/Producer",),
    "acoustid_id": ("Acoustid/Id",),
    "acoustid_fingerprint": ("Acoustid/Fingerprint",),
    "genre": ("WM/Genre",),
    "lyrics_plain": ("WM/Lyrics",),
    "lyrics_synced": ("WM/Lyrics_Synchronised",),
    "replaygain_track_gain": ("REPLAYGAIN_TRACK_GAIN",),
    "replaygain_album_gain": ("REPLAYGAIN_ALBUM_GAIN",),
    "replaygain_track_peak": ("REPLAYGAIN_TRACK_PEAK",),
    "replaygain_album_peak": ("REPLAYGAIN_ALBUM_PEAK",),
}

_RIFF_TEXT_KEYS: dict[str, str] = {
    "album": "IPRD",
    "title": "INAM",
    "artist": "IART",
    "track_number": "ITRK",
    "date": "ICRD",
    "genre": "IGNR",
    "media": "IMED",
    "composer": "IMUS",
    "producer": "IPRO",
}


def _values(value: AudioFieldValue | None) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, str):
        return (value,)
    return ()


def _scalar(value: AudioFieldValue | None) -> str | None:
    values = _values(value)
    return values[0] if values else None


def _integer(value: AudioFieldValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _storage_values(name: str, value: AudioFieldValue | None) -> tuple[str, ...]:
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if name.endswith("_gain"):
            return (f"{float(value):+.6f} dB",)
        if name.endswith("_peak"):
            return (f"{float(value):.9f}",)
    return _values(value)


def _effective_values(plan: AudioWritePlan) -> dict[str, AudioFieldValue | None]:
    values = {field.name: field.value for field in plan.snapshot.metadata.fields}
    for mutation in plan.mutations:
        if mutation.operation not in {"unchanged", "preserve"}:
            values[mutation.name] = mutation.after
    return values


def _changed(plan: AudioWritePlan) -> set[str]:
    return {
        mutation.name
        for mutation in plan.mutations
        if mutation.operation not in {"unchanged", "preserve"}
    }


def _delete_keys(tags: object, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in tags:
            del tags[key]


def _delete_casefold_key(tags: object, key: str) -> None:
    folded = key.casefold()
    for existing in list(tags.keys()):
        if str(existing).casefold() == folded:
            del tags[existing]


def _native_python_value(value: NativeTagValue) -> object:
    if value.kind == "text":
        return value.text or ""
    if value.kind == "integer":
        return value.integer or 0
    if value.kind == "float":
        return value.float_value or 0.0
    if value.kind == "boolean":
        return bool(value.boolean)
    if value.kind == "binary":
        return value.binary or b""
    if value.kind == "integer_pair":
        return tuple(value.integer_pair)
    raise AudioWriteError("A native tag value cannot be restored safely.")


def _restore_vorbis_entries(tags: object, entries: tuple[NativeTagEntry, ...]) -> None:
    tags.clear()
    for entry in entries:
        values = [_native_python_value(value) for value in entry.values]
        if any(not isinstance(value, str) for value in values):
            raise AudioWriteError("A Vorbis snapshot contains a non-text value.")
        tags[entry.key] = values


def _ape_value(value: NativeTagValue):
    raw = _native_python_value(value)
    if value.type_code == 1:
        return APEBinaryValue(raw)
    if value.type_code == 2:
        return APEExtValue(str(raw))
    return APETextValue(str(raw))


def _restore_ape_entries(tags: APEv2, entries: tuple[NativeTagEntry, ...]) -> None:
    tags.clear()
    for entry in entries:
        if len(entry.values) != 1:
            raise AudioWriteError("An APEv2 snapshot item has invalid cardinality.")
        tags[entry.key] = _ape_value(entry.values[0])


def _mp4_value(key: str, value: NativeTagValue) -> object:
    raw = _native_python_value(value)
    if value.kind == "binary":
        if key == "covr":
            image_format = AtomDataType(value.type_code or int(AtomDataType.JPEG))
            return MP4Cover(raw, imageformat=image_format)
        if key.startswith(_MP4_PREFIX):
            data_format = AtomDataType(value.type_code or int(AtomDataType.UTF8))
            return MP4FreeForm(raw, dataformat=data_format)
    return raw


def _restore_mp4_entries(tags: object, entries: tuple[NativeTagEntry, ...]) -> None:
    tags.clear()
    for entry in entries:
        values = [_mp4_value(entry.key, value) for value in entry.values]
        tags[entry.key] = values if entry.container == "list" else values[0]


_ASF_TYPES = {
    0: ASFUnicodeAttribute,
    1: ASFByteArrayAttribute,
    2: ASFBoolAttribute,
    3: ASFDWordAttribute,
    4: ASFQWordAttribute,
    5: ASFWordAttribute,
    6: ASFGUIDAttribute,
}


def _asf_value(value: NativeTagValue):
    raw = _native_python_value(value)
    attribute_type = _ASF_TYPES.get(value.type_code or 0)
    if attribute_type is None:
        raise AudioWriteError("An ASF snapshot contains an unknown attribute type.")
    if attribute_type is ASFGUIDAttribute:
        raw = uuid.UUID(str(raw))
    return attribute_type(value=raw, language=value.language, stream=value.stream)


def _restore_asf_entries(tags: object, entries: tuple[NativeTagEntry, ...]) -> None:
    tags.clear()
    for entry in entries:
        tags[entry.key] = [_asf_value(value) for value in entry.values]


def _id3_from_snapshot(encoded: bytes | None) -> ID3:
    return ID3(BytesIO(encoded)) if encoded else ID3()


def _restore_id3_frames(
    tags: object, encoded: bytes | None, keys: set[str] | None
) -> None:
    tags.clear()
    source = _id3_from_snapshot(encoded)
    for key, frame in source.items():
        if keys is None or key in keys:
            tags.add(frame)


def _ensure_tags(audio: object, audio_format: AudioContainer, path: Path) -> object:
    if audio_format == "aac":
        try:
            return APEv2(path)
        except APEError:
            return APEv2()
    tags = getattr(audio, "tags", None)
    if tags is None:
        audio.add_tags()
        tags = audio.tags
    return tags


def _prepare_tags(
    tags: object,
    audio_format: AudioContainer,
    plan: AudioWritePlan,
) -> None:
    if not plan.scrubbed_raw_keys:
        return
    preserved = set(plan.preserved_raw_keys)
    native = plan.snapshot.native_tags
    if audio_format in {"mp3", "wav"}:
        _restore_id3_frames(tags, native.encoded_id3, preserved)
    else:
        entries = tuple(entry for entry in native.entries if entry.key in preserved)
        if audio_format in {"flac", "ogg", "opus"}:
            _restore_vorbis_entries(tags, entries)
        elif audio_format == "m4a":
            _restore_mp4_entries(tags, entries)
        elif audio_format == "aac":
            _restore_ape_entries(tags, entries)
        else:
            _restore_asf_entries(tags, entries)


def _set_mapping_text(
    tags: object,
    mapping: dict[str, tuple[str, ...]],
    name: str,
    value: AudioFieldValue | None,
    *,
    binary_freeform: bool = False,
) -> None:
    keys = mapping[name]
    _delete_keys(tags, keys)
    values = _storage_values(name, value)
    if not values:
        return
    key = keys[0]
    if binary_freeform and key.startswith(_MP4_PREFIX):
        tags[key] = [MP4FreeForm(item.encode("utf-8")) for item in values]
    else:
        tags[key] = list(values)


def _write_vorbis(
    audio: object, tags: object, plan: AudioWritePlan, values: dict[str, object]
) -> None:
    changed = _changed(plan)
    for name in changed & _VORBIS_TEXT_KEYS.keys():
        _set_mapping_text(tags, _VORBIS_TEXT_KEYS, name, values.get(name))
    if "artist" in changed:
        _delete_keys(tags, ("ARTISTS", "ARTIST"))
        artists = _values(values.get("artist"))
        if artists:
            tags["ARTISTS"] = list(artists)
            tags["ARTIST"] = plan.artist_display or artists[0]
    if "album_artist" in changed:
        _delete_keys(tags, ("ALBUMARTISTS", "ALBUMARTIST"))
        artists = _values(values.get("album_artist"))
        if artists:
            tags["ALBUMARTISTS"] = list(artists)
            tags["ALBUMARTIST"] = plan.album_artist_display or artists[0]
    numeric = {
        "track_number": "TRACKNUMBER",
        "total_tracks": "TOTALTRACKS",
        "disc_number": "DISCNUMBER",
        "total_discs": "TOTALDISCS",
        "movement_number": "MOVEMENT",
        "movement_count": "MOVEMENTTOTAL",
    }
    for name, key in numeric.items():
        if name in changed:
            if key in tags:
                del tags[key]
            value = _integer(values.get(name))
            if value is not None:
                tags[key] = str(value)
    if "compilation" in changed:
        if "COMPILATION" in tags:
            del tags["COMPILATION"]
        value = values.get("compilation")
        if isinstance(value, bool):
            tags["COMPILATION"] = "1" if value else "0"

    if plan.desired_artwork != plan.snapshot.artwork:
        if isinstance(audio, FLAC):
            audio.clear_pictures()
            for image in plan.desired_artwork:
                picture = Picture()
                picture.type = _picture_number(image.image_type)
                picture.mime = image.mime_type or ""
                picture.desc = image.description
                picture.width = image.width or 0
                picture.height = image.height or 0
                picture.data = image.content
                audio.add_picture(picture)
        else:
            if "METADATA_BLOCK_PICTURE" in tags:
                del tags["METADATA_BLOCK_PICTURE"]
            if plan.desired_artwork:
                blocks: list[str] = []
                for image in plan.desired_artwork:
                    picture = Picture()
                    picture.type = _picture_number(image.image_type)
                    picture.mime = image.mime_type or ""
                    picture.desc = image.description
                    picture.width = image.width or 0
                    picture.height = image.height or 0
                    picture.data = image.content
                    blocks.append(base64.b64encode(picture.write()).decode("ascii"))
                tags["METADATA_BLOCK_PICTURE"] = blocks


def _picture_number(image_type: str) -> int:
    return {"front": 3, "back": 4, "booklet": 5, "medium": 6}.get(image_type, 0)


def _set_id3_text(
    tags: object, key: str, frame_type, values: tuple[str, ...], encoding: int
) -> None:
    tags.delall(key)
    if values:
        tags.add(frame_type(encoding=encoding, text=list(values)))


def _write_id3(tags: object, plan: AudioWritePlan, values: dict[str, object]) -> None:
    changed = _changed(plan)
    encoding = 3 if plan.compatibility.id3_text_encoding == "utf8" else 1
    frames = {
        "album": ("TALB", TALB),
        "title": ("TIT2", TIT2),
        "album_sort": ("TSOA", TSOA),
        "title_sort": ("TSOT", TSOT),
        "artist_sort": ("TSOP", TSOP),
        "album_artist_sort": ("TSO2", TSO2),
        "disc_subtitle": ("TSST", TSST),
        "date": ("TDRC", TDRC),
        "original_date": ("TDOR", TDOR),
        "media": ("TMED", TMED),
        "label": ("TPUB", TPUB),
        "isrc": ("TSRC", TSRC),
        "movement": ("MVNM", MVNM),
        "composer": ("TCOM", TCOM),
        "lyricist": ("TEXT", TEXT),
        "conductor": ("TPE3", TPE3),
        "remixer": ("TPE4", TPE4),
        "genre": ("TCON", TCON),
    }
    for name in changed & frames.keys():
        key, frame_type = frames[name]
        _set_id3_text(tags, key, frame_type, _values(values.get(name)), encoding)
    if "label" in changed:
        tags.delall("TXXX:LABEL")
    if "artist" in changed:
        _set_id3_text(
            tags,
            "TPE1",
            TPE1,
            (plan.artist_display or _scalar(values.get("artist")) or "",),
            encoding,
        )
        tags.delall("TXXX:Artists")
        artists = _values(values.get("artist"))
        if artists:
            tags.add(TXXX(encoding=encoding, desc="Artists", text=list(artists)))
    if "album_artist" in changed:
        _set_id3_text(tags, "TPE2", TPE2, _values(values.get("album_artist")), encoding)
    if changed & {"track_number", "total_tracks"}:
        number = _integer(values.get("track_number"))
        total = _integer(values.get("total_tracks"))
        text = (
            f"{number}/{total}" if number is not None and total else str(number or "")
        )
        _set_id3_text(tags, "TRCK", TRCK, (text,) if text else (), encoding)
    if changed & {"disc_number", "total_discs"}:
        number = _integer(values.get("disc_number"))
        total = _integer(values.get("total_discs"))
        text = (
            f"{number}/{total}" if number is not None and total else str(number or "")
        )
        _set_id3_text(tags, "TPOS", TPOS, (text,) if text else (), encoding)
    if changed & {"movement_number", "movement_count"}:
        number = _integer(values.get("movement_number"))
        total = _integer(values.get("movement_count"))
        text = (
            f"{number}/{total}" if number is not None and total else str(number or "")
        )
        _set_id3_text(tags, "MVIN", MVIN, (text,) if text else (), encoding)
    if "compilation" in changed:
        value = values.get("compilation")
        _set_id3_text(
            tags,
            "TCMP",
            TCMP,
            (("1" if value else "0"),) if isinstance(value, bool) else (),
            encoding,
        )
    txxx = {
        "release_status": "MusicBrainz Album Status",
        "release_country": "MusicBrainz Album Release Country",
        "release_type": "MusicBrainz Album Type",
        "catalog_number": "CATALOGNUMBER",
        "barcode": "BARCODE",
        "asin": "ASIN",
        "musicbrainz_release_track_id": "MusicBrainz Release Track Id",
        "musicbrainz_release_id": "MusicBrainz Album Id",
        "musicbrainz_release_group_id": "MusicBrainz Release Group Id",
        "musicbrainz_artist_id": "MusicBrainz Artist Id",
        "musicbrainz_album_artist_id": "MusicBrainz Album Artist Id",
        "work": "WORK",
        "musicbrainz_work_id": "MusicBrainz Work Id",
        "acoustid_id": "Acoustid Id",
        "acoustid_fingerprint": "Acoustid Fingerprint",
        "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
        "replaygain_album_gain": "REPLAYGAIN_ALBUM_GAIN",
        "replaygain_track_peak": "REPLAYGAIN_TRACK_PEAK",
        "replaygain_album_peak": "REPLAYGAIN_ALBUM_PEAK",
    }
    for name in changed & txxx.keys():
        description = txxx[name]
        tags.delall(f"TXXX:{description}")
        field_values = _storage_values(name, values.get(name))
        if field_values:
            tags.add(TXXX(encoding=encoding, desc=description, text=list(field_values)))
    if "lyrics_plain" in changed:
        tags.delall("USLT")
        value = _scalar(values.get("lyrics_plain"))
        if value:
            tags.add(USLT(encoding=encoding, lang="eng", desc="", text=value))
    if "lyrics_synced" in changed:
        tags.delall("SYLT")
        value = _scalar(values.get("lyrics_synced"))
        entries = parse_lrc(value) if value else ()
        if entries:
            tags.add(
                SYLT(
                    encoding=encoding,
                    lang="eng",
                    format=2,
                    type=1,
                    desc="",
                    text=list(entries),
                )
            )
    if "musicbrainz_recording_id" in changed:
        tags.delall(f"UFID:{_MB_UFID_OWNER}")
        value = _scalar(values.get("musicbrainz_recording_id"))
        if value:
            tags.add(UFID(owner=_MB_UFID_OWNER, data=value.encode("utf-8")))
    if "performer" in changed:
        tags.delall("TMCL")
        performers = _values(values.get("performer"))
        if performers:
            people: list[list[str]] = []
            for value in performers:
                person, separator, suffix = value.rpartition(" (")
                people.append(
                    [suffix[:-1], person]
                    if separator and suffix.endswith(")")
                    else ["", value]
                )
            tags.add(TMCL(encoding=encoding, people=people))
    if changed & {"arranger", "producer"}:
        tags.delall("TIPL")
        tags.delall("IPLS")
        if "arranger" in changed:
            tags.delall("TXXX:ARRANGER")
        if "producer" in changed:
            tags.delall("TXXX:PRODUCER")
        people = [
            [role, value]
            for role in ("arranger", "producer")
            for value in _values(values.get(role))
        ]
        if people:
            tags.add(TIPL(encoding=encoding, people=people))
    if plan.desired_artwork != plan.snapshot.artwork:
        tags.delall("APIC")
        for image in plan.desired_artwork:
            tags.add(
                APIC(
                    encoding=encoding,
                    mime=image.mime_type or "application/octet-stream",
                    type=_picture_number(image.image_type),
                    desc=image.description,
                    data=image.content,
                )
            )


def _write_mp4(tags: object, plan: AudioWritePlan, values: dict[str, object]) -> None:
    changed = _changed(plan)
    for name in changed & _MP4_TEXT_KEYS.keys():
        _set_mapping_text(
            tags,
            _MP4_TEXT_KEYS,
            name,
            values.get(name),
            binary_freeform=True,
        )
    if "artist" in changed:
        _delete_keys(tags, ("©ART", f"{_MP4_PREFIX}ARTISTS"))
        artists = _values(values.get("artist"))
        if artists:
            tags["©ART"] = [plan.artist_display or artists[0]]
            tags[f"{_MP4_PREFIX}ARTISTS"] = [
                MP4FreeForm(value.encode()) for value in artists
            ]
    if "album_artist" in changed:
        _delete_keys(tags, ("aART",))
        artists = _values(values.get("album_artist"))
        if artists:
            tags["aART"] = list(artists)
    if changed & {"track_number", "total_tracks"}:
        number = _integer(values.get("track_number")) or 0
        total = _integer(values.get("total_tracks")) or 0
        tags["trkn"] = [(number, total)] if number or total else []
    if changed & {"disc_number", "total_discs"}:
        number = _integer(values.get("disc_number")) or 0
        total = _integer(values.get("total_discs")) or 0
        tags["disk"] = [(number, total)] if number or total else []
    for name, key in (("movement_number", "©mvi"), ("movement_count", "©mvc")):
        if name in changed:
            value = _integer(values.get(name))
            if value is None:
                tags.pop(key, None)
            else:
                tags[key] = [value]
    if "compilation" in changed:
        value = values.get("compilation")
        if isinstance(value, bool):
            tags["cpil"] = value
        else:
            tags.pop("cpil", None)
    if plan.desired_artwork != plan.snapshot.artwork:
        if plan.desired_artwork:
            tags["covr"] = [
                MP4Cover(
                    image.content,
                    imageformat=(
                        MP4Cover.FORMAT_PNG
                        if image.mime_type == "image/png"
                        else MP4Cover.FORMAT_JPEG
                    ),
                )
                for image in plan.desired_artwork
            ]
        else:
            tags.pop("covr", None)


def _write_ape(tags: APEv2, plan: AudioWritePlan, values: dict[str, object]) -> None:
    changed = _changed(plan)
    for name in changed & _APE_TEXT_KEYS.keys():
        keys = _APE_TEXT_KEYS[name]
        _delete_keys(tags, keys)
        field_values = _storage_values(name, values.get(name))
        if field_values:
            tags[keys[0]] = APETextValue("\x00".join(field_values))
    if "artist" in changed:
        _delete_keys(tags, ("Artist", "Artists"))
        artists = _values(values.get("artist"))
        if artists:
            tags["Artist"] = APETextValue(plan.artist_display or artists[0])
            tags["Artists"] = APETextValue("\x00".join(artists))
    if "album_artist" in changed:
        _delete_keys(tags, ("Album Artist",))
        artists = _values(values.get("album_artist"))
        if artists:
            tags["Album Artist"] = APETextValue("\x00".join(artists))
    if changed & {"track_number", "total_tracks"}:
        number = _integer(values.get("track_number"))
        total = _integer(values.get("total_tracks"))
        text = (
            f"{number}/{total}" if number is not None and total else str(number or "")
        )
        if text:
            tags["Track"] = APETextValue(text)
        else:
            tags.pop("Track", None)
    if changed & {"disc_number", "total_discs"}:
        number = _integer(values.get("disc_number"))
        total = _integer(values.get("total_discs"))
        text = (
            f"{number}/{total}" if number is not None and total else str(number or "")
        )
        if text:
            tags["Disc"] = APETextValue(text)
        else:
            tags.pop("Disc", None)
    for name, key in (
        ("movement_number", "MOVEMENT"),
        ("movement_count", "MOVEMENTTOTAL"),
    ):
        if name in changed:
            value = _integer(values.get(name))
            if value is None:
                tags.pop(key, None)
            else:
                tags[key] = APETextValue(str(value))
    if "compilation" in changed:
        value = values.get("compilation")
        if isinstance(value, bool):
            tags["Compilation"] = APETextValue("1" if value else "0")
        else:
            tags.pop("Compilation", None)
    if plan.desired_artwork != plan.snapshot.artwork:
        for key in list(tags.keys()):
            if str(key).casefold().startswith("cover art ("):
                del tags[key]
        type_names = {"front": "Front", "back": "Back", "medium": "Media"}
        for position, image in enumerate(plan.desired_artwork):
            name = type_names.get(image.image_type, f"Other {position + 1}")
            extension = {
                "image/png": "png",
                "image/webp": "webp",
                "image/gif": "gif",
            }.get(image.mime_type or "", "jpg")
            payload = f"cover.{extension}".encode() + b"\x00" + image.content
            tags[f"Cover Art ({name})"] = APEBinaryValue(payload)


def _write_asf(tags: object, plan: AudioWritePlan, values: dict[str, object]) -> None:
    changed = _changed(plan)
    for name in changed & _ASF_TEXT_KEYS.keys():
        keys = _ASF_TEXT_KEYS[name]
        _delete_keys(tags, keys)
        field_values = _storage_values(name, values.get(name))
        if field_values:
            tags[keys[0]] = list(field_values)
    if "artist" in changed:
        _delete_keys(tags, ("Author", "WM/ARTISTS"))
        artists = _values(values.get("artist"))
        if artists:
            tags["Author"] = [plan.artist_display or artists[0]]
            tags["WM/ARTISTS"] = list(artists)
    if "album_artist" in changed:
        _delete_keys(tags, ("WM/AlbumArtist",))
        artists = _values(values.get("album_artist"))
        if artists:
            tags["WM/AlbumArtist"] = list(artists)
    if "track_number" in changed:
        number = _integer(values.get("track_number"))
        tags["WM/TrackNumber"] = [str(number)] if number is not None else []
    if changed & {"disc_number", "total_discs"}:
        number = _integer(values.get("disc_number"))
        total = _integer(values.get("total_discs"))
        text = (
            f"{number}/{total}" if number is not None and total else str(number or "")
        )
        tags["WM/PartOfSet"] = [text] if text else []
    if "compilation" in changed:
        value = values.get("compilation")
        tags["WM/IsCompilation"] = (
            ["1" if value else "0"] if isinstance(value, bool) else []
        )
    if plan.desired_artwork != plan.snapshot.artwork:
        if plan.desired_artwork:
            tags["WM/Picture"] = [
                ASFByteArrayAttribute(_asf_picture(image))
                for image in plan.desired_artwork
            ]
        else:
            tags.pop("WM/Picture", None)


def _write_custom_tags(tags: object, plan: AudioWritePlan) -> None:
    for mutation in plan.custom_tag_mutations:
        if mutation.operation == "preserve":
            continue
        key = mutation.native_key
        _delete_casefold_key(tags, key)
        if not mutation.after:
            continue
        if plan.audio_format in {"flac", "ogg", "opus"}:
            tags[key] = list(mutation.after)
        elif plan.audio_format in {"mp3", "wav"}:
            description = key.removeprefix("TXXX:")
            encoding = 3 if plan.compatibility.id3_text_encoding == "utf8" else 1
            tags.add(
                TXXX(encoding=encoding, desc=description, text=list(mutation.after))
            )
        elif plan.audio_format == "m4a":
            tags[key] = [MP4FreeForm(value.encode("utf-8")) for value in mutation.after]
        elif plan.audio_format == "aac":
            tags[key] = APETextValue("\x00".join(mutation.after))
        else:
            tags[key] = list(mutation.after)


def _write_riff(path: Path, plan: AudioWritePlan, values: dict[str, object]) -> None:
    existing = read_riff_info(path)
    if plan.scrubbed_raw_keys:
        preserved = set(plan.preserved_raw_keys)
        existing = {
            key: value
            for key, value in existing.items()
            if f"RIFF_INFO:{key}" in preserved
        }
    changed = _changed(plan)
    for name in changed & _RIFF_TEXT_KEYS.keys():
        key = _RIFF_TEXT_KEYS[name]
        value = values.get(name)
        if name == "artist":
            rendered = plan.artist_display or _scalar(value)
        elif name == "track_number":
            number = _integer(value)
            rendered = str(number) if number is not None else None
        else:
            rendered = _scalar(value)
        if rendered:
            existing[key] = (rendered,)
        else:
            existing.pop(key, None)
    for mutation in plan.custom_tag_mutations:
        if mutation.operation == "preserve":
            continue
        key = mutation.native_key.removeprefix("RIFF_INFO:")
        if mutation.after:
            existing[key] = mutation.after
        else:
            existing.pop(key, None)
    write_riff_info(path, existing)


def _scrub_riff(path: Path, plan: AudioWritePlan) -> None:
    scrubbed = {
        key.removeprefix("RIFF_INFO:")
        for key in plan.scrubbed_raw_keys
        if key.startswith("RIFF_INFO:")
    }
    if not scrubbed:
        return
    existing = read_riff_info(path)
    write_riff_info(
        path,
        {key: values for key, values in existing.items() if key not in scrubbed},
    )


def _asf_picture(image: EmbeddedArtworkDescriptor) -> bytes:
    mime = f"{image.mime_type or ''}\x00".encode("utf-16-le")
    description = f"{image.description}\x00".encode("utf-16-le")
    return (
        bytes([_picture_number(image.image_type)])
        + struct.pack("<I", len(image.content))
        + mime
        + description
        + image.content
    )


def _open_audio(path: Path, audio_format: AudioContainer) -> object:
    return {
        "flac": FLAC,
        "mp3": MP3,
        "ogg": OggVorbis,
        "opus": OggOpus,
        "m4a": MP4,
        "aac": AAC,
        "wav": WAVE,
        "wma": ASF,
    }[audio_format](path)


def _save_audio(
    path: Path,
    audio: object,
    tags: object,
    plan: AudioWritePlan,
) -> None:
    if plan.audio_format == "aac":
        if "remove_apev2_from_aac" in plan.cleanup_actions:
            return
        tags.save(path)
        return
    if plan.audio_format in {"mp3", "wav"}:
        kwargs = {"v2_version": 3 if plan.compatibility.id3_version == "2.3" else 4}
        if plan.compatibility.id3_version == "2.3":
            kwargs["v23_sep"] = plan.compatibility.id3v23_join_delimiter or "; "
        audio.save(**kwargs)
        return
    if plan.audio_format == "flac":
        audio.save(deleteid3="remove_id3_from_flac" in plan.cleanup_actions)
        return
    audio.save()


def _apply_file_attributes(path: Path, plan: AudioWritePlan) -> None:
    attributes = plan.snapshot.file_attributes
    if plan.preserve_permissions:
        os.chmod(path, attributes.permission_bits)
    if plan.preserve_timestamps:
        os.utime(path, ns=(attributes.atime_ns, attributes.mtime_ns))


def _fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_technical(before: ReadAudioDocument, after: ReadAudioDocument) -> None:
    expected = before.technical
    actual = after.technical
    if (
        expected.sample_rate_hz != actual.sample_rate_hz
        or expected.channels != actual.channels
        or expected.bit_depth != actual.bit_depth
    ):
        raise AudioWriteError(
            "Staged metadata writing changed technical audio properties."
        )
    if (
        before.probe.detected_format != "aac"
        and abs(expected.duration_seconds - actual.duration_seconds) > 0.01
    ):
        raise AudioWriteError("Staged metadata writing changed audio duration.")


def _validate_result(plan: AudioWritePlan, result: ReadAudioDocument) -> None:
    for mutation in plan.mutations:
        expected = (
            mutation.after
            if mutation.operation not in {"unchanged", "preserve"}
            else mutation.before
        )
        actual = result.metadata.value_for(mutation.name)
        if actual != expected and not (expected == () and actual is None):
            raise AudioWriteError(
                f"Staged metadata validation did not match {mutation.name}."
            )
    raw_values = {raw.key.casefold(): raw.values for raw in result.raw_tags}
    for mutation in plan.custom_tag_mutations:
        expected = (
            mutation.before if mutation.operation == "preserve" else mutation.after
        )
        if raw_values.get(mutation.native_key.casefold(), ()) != expected:
            raise AudioWriteError(
                "Staged custom-tag validation did not match the plan."
            )
    expected_art = sorted(
        (image.image_type, image.mime_type or "", image.sha256)
        for image in plan.desired_artwork
    )
    actual_art = sorted(
        (image.image_type, image.mime_type or "", image.sha256)
        for image in result.artwork
    )
    if expected_art != actual_art:
        raise AudioWriteError("Staged artwork validation did not match the plan.")
    _validate_technical(
        ReadAudioDocument(
            probe=plan.snapshot.probe,
            metadata=plan.snapshot.metadata,
            artwork=plan.snapshot.artwork,
            technical=plan.snapshot.technical,
            raw_tags=plan.snapshot.raw_tags,
            native_tags=plan.snapshot.native_tags,
            file_attributes=plan.snapshot.file_attributes,
        ),
        result,
    )


def apply_plan(engine, path: Path, plan: AudioWritePlan) -> AudioWriteResult:
    if plan.blockers:
        raise AudioWriteError("The staged write plan contains capability blockers.")
    try:
        current = engine.read(path)
        if (
            current.probe.detected_format != plan.audio_format
            or current.native_tags != plan.snapshot.native_tags
        ):
            raise AudioWriteError("The staged file no longer matches its write plan.")
        if plan.requires_write:
            audio = _open_audio(path, plan.audio_format)
            values = _effective_values(plan)
            riff_mode = (
                plan.audio_format == "wav"
                and plan.compatibility.wav_tag_policy == "riff_info"
            )
            tags = getattr(audio, "tags", None) if riff_mode else None
            needs_riff_id3_write = riff_mode and (
                tags is not None
                or (
                    plan.desired_artwork != plan.snapshot.artwork
                    and bool(plan.desired_artwork)
                )
            )
            if not riff_mode or needs_riff_id3_write:
                tags = _ensure_tags(audio, plan.audio_format, path)
                _prepare_tags(tags, plan.audio_format, plan)

            if plan.audio_format in {"flac", "ogg", "opus"}:
                _write_vorbis(audio, tags, plan, values)
            elif riff_mode and tags is not None:
                if plan.desired_artwork != plan.snapshot.artwork:
                    tags.delall("APIC")
                    for image in plan.desired_artwork:
                        tags.add(
                            APIC(
                                encoding=3,
                                mime=image.mime_type or "application/octet-stream",
                                type=_picture_number(image.image_type),
                                desc=image.description,
                                data=image.content,
                            )
                        )
            elif riff_mode:
                pass
            elif plan.audio_format in {"mp3", "wav"}:
                _write_id3(tags, plan, values)
            elif plan.audio_format == "m4a":
                _write_mp4(tags, plan, values)
            elif plan.audio_format == "aac":
                if "remove_apev2_from_aac" in plan.cleanup_actions:
                    delete_apev2(path)
                else:
                    _write_ape(tags, plan, values)
            else:
                _write_asf(tags, plan, values)
            if not riff_mode:
                _write_custom_tags(tags, plan)
            if "remove_apev2_from_mp3" in plan.cleanup_actions:
                delete_apev2(path)
            if not riff_mode or needs_riff_id3_write:
                _save_audio(path, audio, tags, plan)
            if riff_mode:
                _write_riff(path, plan, values)
            elif plan.audio_format == "wav":
                _scrub_riff(path, plan)
            _apply_file_attributes(path, plan)
            _fsync(path)
        result = engine.read(path)
        _validate_result(plan, result)
        file_sha256 = _hash_file(path)
        _apply_file_attributes(path, plan)
        return AudioWriteResult(
            document=result,
            file_sha256=file_sha256,
            file_size_bytes=path.stat().st_size,
            warnings=plan.warnings,
        )
    except AudioWriteError:
        raise
    except (
        AudioFormatMismatchError,
        MutagenError,
        OSError,
        TypeError,
        UnsupportedAudioFormatError,
        ValueError,
    ) as error:
        raise AudioWriteError(
            "The staged audio file could not be written safely."
        ) from error


def _restore_primary(path: Path, snapshot: SemanticTagSnapshot) -> None:
    audio_format = snapshot.probe.detected_format
    if audio_format is None:
        raise AudioWriteError("The snapshot has no restorable audio format.")
    audio = _open_audio(path, audio_format)
    native = snapshot.native_tags
    if audio_format in {"mp3", "wav"}:
        if native.encoded_id3 is not None:
            tags = _ensure_tags(audio, audio_format, path)
            _restore_id3_frames(tags, native.encoded_id3, None)
            version = 3 if snapshot.probe.tag_version == "2.3.0" else 4
            audio.save(v2_version=version)
        elif getattr(audio, "tags", None) is not None:
            audio.delete()
        if audio_format == "wav":
            riff_values: dict[str, tuple[str, ...]] = {}
            if native.auxiliary_storage_kind == "riff_info":
                riff_values = {
                    entry.key: tuple(
                        str(_native_python_value(value)) for value in entry.values
                    )
                    for entry in native.auxiliary_entries
                }
            write_riff_info(path, riff_values)
    elif audio_format in {"flac", "ogg", "opus"}:
        tags = _ensure_tags(audio, audio_format, path)
        _restore_vorbis_entries(tags, native.entries)
        if audio_format == "flac":
            audio.clear_pictures()
            for image in snapshot.artwork:
                picture = Picture()
                picture.type = _picture_number(image.image_type)
                picture.mime = image.mime_type or ""
                picture.desc = image.description
                picture.width = image.width or 0
                picture.height = image.height or 0
                picture.data = image.content
                audio.add_picture(picture)
        audio.save(deleteid3=True) if audio_format == "flac" else audio.save()
    elif audio_format == "m4a":
        tags = _ensure_tags(audio, audio_format, path)
        _restore_mp4_entries(tags, native.entries)
        audio.save()
    elif audio_format == "aac":
        if native.entries:
            tags = _ensure_tags(audio, audio_format, path)
            _restore_ape_entries(tags, native.entries)
            tags.save(path)
        else:
            try:
                delete_apev2(path)
            except APEError:
                pass
    else:
        tags = _ensure_tags(audio, audio_format, path)
        _restore_asf_entries(tags, native.entries)
        audio.save()

    if audio_format == "mp3":
        if native.auxiliary_entries:
            auxiliary = APEv2()
            _restore_ape_entries(auxiliary, native.auxiliary_entries)
            auxiliary.save(path)
        else:
            try:
                delete_apev2(path)
            except APEError:
                pass
    if audio_format == "flac" and native.auxiliary_encoded_id3:
        _id3_from_snapshot(native.auxiliary_encoded_id3).save(path, v1=0)


def restore_snapshot(
    engine, path: Path, snapshot: SemanticTagSnapshot
) -> AudioWriteResult:
    try:
        before = engine.read(path)
        if before.probe.detected_format != snapshot.probe.detected_format:
            raise AudioWriteError("The staged file does not match the snapshot format.")
        _restore_primary(path, snapshot)
        os.chmod(path, snapshot.file_attributes.permission_bits)
        os.utime(
            path,
            ns=(snapshot.file_attributes.atime_ns, snapshot.file_attributes.mtime_ns),
        )
        _fsync(path)
        result = engine.read(path)
        if (
            result.metadata != snapshot.metadata
            or result.artwork != snapshot.artwork
            or result.native_tags != snapshot.native_tags
        ):
            raise AudioWriteError(
                "The restored staged metadata did not match its snapshot."
            )
        _validate_technical(before, result)
        file_sha256 = _hash_file(path)
        os.utime(
            path,
            ns=(snapshot.file_attributes.atime_ns, snapshot.file_attributes.mtime_ns),
        )
        return AudioWriteResult(
            document=result,
            file_sha256=file_sha256,
            file_size_bytes=path.stat().st_size,
        )
    except AudioWriteError:
        raise
    except (
        AudioFormatMismatchError,
        MutagenError,
        OSError,
        TypeError,
        UnsupportedAudioFormatError,
        ValueError,
    ) as error:
        raise AudioWriteError(
            "The staged audio snapshot could not be restored safely."
        ) from error
