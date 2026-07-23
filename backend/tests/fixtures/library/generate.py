"""Generate the committed audio fixtures used by the Phase 3 library tests.

Run from a dev box with ffmpeg installed (``python generate.py``); the produced
files are small (~0.3s silence, a few KB) and committed to the repo, so the
tests themselves only need mutagen to read them - never ffmpeg.

Tags are written with **raw mutagen** (not AudioTagger) on purpose: the tagger
tests must validate against an independent oracle, otherwise a symmetric
read/write bug would hide.

Idempotent: deletes and regenerates the whole set on every run.
"""

import base64
from io import BytesIO
from pathlib import Path
import struct
import subprocess

from PIL import Image
from mutagen.apev2 import APEBinaryValue, APEv2
from mutagen.asf import ASF, ASFByteArrayAttribute
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    ID3,
    TALB,
    TCMP,
    TCOM,
    TCON,
    TDRC,
    TDOR,
    TEXT,
    TIPL,
    TIT2,
    TMED,
    TPE1,
    TPE2,
    TPOS,
    TPUB,
    TRCK,
    TSO2,
    TSOA,
    TSOP,
    TSOT,
    TSRC,
    TSST,
    TXXX,
    UFID,
    APIC,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

FIXTURES = Path(__file__).resolve().parent

# Picard tag names, mirrored here independently of the app's tagger. The recording
# MBID lives in Vorbis MUSICBRAINZ_TRACKID / ID3 UFID:musicbrainz.org / MP4
# "MusicBrainz Track Id" - NOT the "Release Track Id" tags.
_MB_UFID_OWNER = "http://musicbrainz.org"
_VORBIS = {
    "musicbrainz_release_group_id": "MUSICBRAINZ_RELEASEGROUPID",
    "musicbrainz_release_id": "MUSICBRAINZ_ALBUMID",
    "musicbrainz_recording_id": "MUSICBRAINZ_TRACKID",
    "musicbrainz_artist_id": "MUSICBRAINZ_ARTISTID",
    "musicbrainz_album_artist_id": "MUSICBRAINZ_ALBUMARTISTID",
    "acoustid_id": "ACOUSTID_ID",
}
# TXXX descriptions (recording id is written as a UFID frame, handled separately).
_ID3 = {
    "musicbrainz_release_group_id": "MusicBrainz Release Group Id",
    "musicbrainz_release_id": "MusicBrainz Album Id",
    "musicbrainz_artist_id": "MusicBrainz Artist Id",
    "musicbrainz_album_artist_id": "MusicBrainz Album Artist Id",
    "acoustid_id": "Acoustid Id",
}
_MP4_PREFIX = "----:com.apple.iTunes:"
_MP4 = {field: f"{_MP4_PREFIX}{desc}" for field, desc in _ID3.items()}
_MP4["musicbrainz_recording_id"] = f"{_MP4_PREFIX}MusicBrainz Track Id"

_MANAGEMENT_TAGS = {
    "title": "Management Track",
    "artist": "Alpha feat. Beta",
    "artists": ["Alpha", "Beta"],
    "album": "Management Album",
    "title_sort": "Management Track, The",
    "album_sort": "Management Album, The",
    "album_artist": "Alpha",
    "track_number": 2,
    "total_tracks": 9,
    "disc_number": 1,
    "total_discs": 2,
    "date": "2024-03-02",
    "original_date": "2020",
    "genres": ["Electronic", "Ambient"],
    "release_status": "Official",
    "release_country": "GB",
    "release_types": ["Album", "Compilation"],
    "media": "Digital Media",
    "label": "Example Label",
    "catalog_number": "CAT-42",
    "barcode": "1234567890123",
    "isrc": "GBABC2400001",
    "musicbrainz_release_group_id": "10000000-0000-4000-8000-000000000001",
    "musicbrainz_release_id": "10000000-0000-4000-8000-000000000002",
    "musicbrainz_recording_id": "10000000-0000-4000-8000-000000000003",
    "musicbrainz_release_track_id": "10000000-0000-4000-8000-000000000004",
    "musicbrainz_artist_ids": [
        "10000000-0000-4000-8000-000000000005",
        "10000000-0000-4000-8000-000000000006",
    ],
    "musicbrainz_album_artist_ids": ["10000000-0000-4000-8000-000000000005"],
    "work": "Example Work",
    "musicbrainz_work_id": "10000000-0000-4000-8000-000000000007",
    "disc_subtitle": "Main Programme",
    "composer": "Example Composer",
    "lyricist": "Example Lyricist",
    "producer": "Example Producer",
    "acoustid_id": "10000000-0000-4000-8000-000000000008",
    "acoustid_fingerprint": "AQAD-management-fingerprint",
}


def _cover_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), (20, 80, 140)).save(output, format="PNG")
    return output.getvalue()


def _picture_block() -> Picture:
    picture = Picture()
    picture.type = 3
    picture.mime = "image/png"
    picture.desc = "Front cover"
    picture.width = 4
    picture.height = 3
    picture.depth = 24
    picture.data = _cover_png()
    return picture


def _vorbis_management_pairs() -> list[tuple[str, list[str]]]:
    tags = _MANAGEMENT_TAGS
    return [
        ("TITLE", [tags["title"]]),
        ("ARTIST", [tags["artist"]]),
        ("ARTISTS", tags["artists"]),
        ("ALBUM", [tags["album"]]),
        ("TITLESORT", [tags["title_sort"]]),
        ("ALBUMSORT", [tags["album_sort"]]),
        ("ALBUMARTIST", [tags["album_artist"]]),
        ("ARTISTSORT", ["Alpha, The", "Beta, The"]),
        ("ALBUMARTISTSORT", ["Alpha, The"]),
        ("TRACKNUMBER", [str(tags["track_number"])]),
        ("TOTALTRACKS", [str(tags["total_tracks"])]),
        ("DISCNUMBER", [str(tags["disc_number"])]),
        ("TOTALDISCS", [str(tags["total_discs"])]),
        ("DISCSUBTITLE", [tags["disc_subtitle"]]),
        ("DATE", [tags["date"]]),
        ("ORIGINALDATE", [tags["original_date"]]),
        ("GENRE", tags["genres"]),
        ("RELEASESTATUS", [tags["release_status"]]),
        ("RELEASECOUNTRY", [tags["release_country"]]),
        ("RELEASETYPE", tags["release_types"]),
        ("MEDIA", [tags["media"]]),
        ("COMPILATION", ["1"]),
        ("LABEL", [tags["label"]]),
        ("CATALOGNUMBER", [tags["catalog_number"]]),
        ("BARCODE", [tags["barcode"]]),
        ("ISRC", [tags["isrc"]]),
        ("MUSICBRAINZ_RELEASEGROUPID", [tags["musicbrainz_release_group_id"]]),
        ("MUSICBRAINZ_ALBUMID", [tags["musicbrainz_release_id"]]),
        ("MUSICBRAINZ_TRACKID", [tags["musicbrainz_recording_id"]]),
        ("MUSICBRAINZ_RELEASETRACKID", [tags["musicbrainz_release_track_id"]]),
        ("MUSICBRAINZ_ARTISTID", tags["musicbrainz_artist_ids"]),
        ("MUSICBRAINZ_ALBUMARTISTID", tags["musicbrainz_album_artist_ids"]),
        ("WORK", [tags["work"]]),
        ("MUSICBRAINZ_WORKID", [tags["musicbrainz_work_id"]]),
        ("COMPOSER", [tags["composer"]]),
        ("LYRICIST", [tags["lyricist"]]),
        ("PRODUCER", [tags["producer"]]),
        ("ACOUSTID_ID", [tags["acoustid_id"]]),
        ("ACOUSTID_FINGERPRINT", [tags["acoustid_fingerprint"]]),
        ("CUSTOM_KEEP", ["opaque local value"]),
    ]


def _silence(path: Path, codec: str, extra: list[str]) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            "0.3",
            "-c:a",
            codec,
            *extra,
            str(path),
        ],
        check=True,
    )


def _write_flac(path: Path, tags: dict) -> None:
    _silence(path, "flac", ["-sample_fmt", "s16"])
    audio = FLAC(path)
    audio.delete()
    for key, value in _vorbis_pairs(tags):
        audio[key] = value
    audio.save()


def _write_mp3(path: Path, tags: dict) -> None:
    _silence(path, "libmp3lame", ["-b:a", "320k"])
    audio = ID3()
    audio.add(TIT2(encoding=3, text=[tags["title"]]))
    audio.add(TPE1(encoding=3, text=[tags["artist"]]))
    audio.add(TALB(encoding=3, text=[tags["album"]]))
    if tags.get("album_artist"):
        audio.add(TPE2(encoding=3, text=[tags["album_artist"]]))
    audio.add(TRCK(encoding=3, text=[str(tags["track_number"])]))
    audio.add(TPOS(encoding=3, text=[str(tags.get("disc_number", 1))]))
    if tags.get("year"):
        audio.add(TDRC(encoding=3, text=[str(tags["year"])]))
    if tags.get("genre"):
        audio.add(TCON(encoding=3, text=[tags["genre"]]))
    audio.add(TCMP(encoding=3, text=["1" if tags.get("compilation") else "0"]))
    for field, desc in _ID3.items():
        if tags.get(field):
            audio.add(TXXX(encoding=3, desc=desc, text=[tags[field]]))
    if tags.get("musicbrainz_recording_id"):
        audio.add(
            UFID(
                owner=_MB_UFID_OWNER,
                data=tags["musicbrainz_recording_id"].encode("utf-8"),
            )
        )
    audio.save(path)


def _write_m4a(path: Path, tags: dict) -> None:
    _silence(path, "aac", ["-b:a", "256k"])
    audio = MP4(path)
    audio["\xa9nam"] = [tags["title"]]
    audio["\xa9ART"] = [tags["artist"]]
    audio["\xa9alb"] = [tags["album"]]
    if tags.get("album_artist"):
        audio["aART"] = [tags["album_artist"]]
    audio["trkn"] = [(tags["track_number"], 0)]
    audio["disk"] = [(tags.get("disc_number", 1), 0)]
    if tags.get("year"):
        audio["\xa9day"] = [str(tags["year"])]
    if tags.get("genre"):
        audio["\xa9gen"] = [tags["genre"]]
    audio["cpil"] = bool(tags.get("compilation"))
    for field, key in _MP4.items():
        if tags.get(field):
            audio[key] = [tags[field].encode("utf-8")]
    audio.save()


def _write_management_flac(path: Path) -> None:
    _silence(path, "flac", ["-sample_fmt", "s16"])
    audio = FLAC(path)
    audio.delete()
    for key, values in _vorbis_management_pairs():
        audio[key] = values
    audio.add_picture(_picture_block())
    audio.save()


def _write_management_ogg(path: Path, *, opus: bool) -> None:
    _silence(
        path,
        "libopus" if opus else "libvorbis",
        ["-b:a", "96k" if opus else "128k"],
    )
    audio = OggOpus(path) if opus else OggVorbis(path)
    for key, values in _vorbis_management_pairs():
        audio[key] = values
    picture = base64.b64encode(_picture_block().write()).decode("ascii")
    audio["METADATA_BLOCK_PICTURE"] = [picture]
    audio.save()


def _id3_management_tags():
    tags = _MANAGEMENT_TAGS
    id3 = ID3()
    id3.add(TIT2(encoding=3, text=[tags["title"]]))
    id3.add(TPE1(encoding=3, text=[tags["artist"]]))
    id3.add(TXXX(encoding=3, desc="Artists", text=tags["artists"]))
    id3.add(TALB(encoding=3, text=[tags["album"]]))
    id3.add(TSOT(encoding=3, text=[tags["title_sort"]]))
    id3.add(TSOA(encoding=3, text=[tags["album_sort"]]))
    id3.add(TPE2(encoding=3, text=[tags["album_artist"]]))
    id3.add(TSOP(encoding=3, text=["Alpha, The", "Beta, The"]))
    id3.add(TSO2(encoding=3, text=["Alpha, The"]))
    id3.add(TRCK(encoding=3, text=[f'{tags["track_number"]}/{tags["total_tracks"]}']))
    id3.add(TPOS(encoding=3, text=[f'{tags["disc_number"]}/{tags["total_discs"]}']))
    id3.add(TSST(encoding=3, text=[tags["disc_subtitle"]]))
    id3.add(TDRC(encoding=3, text=[tags["date"]]))
    id3.add(TDOR(encoding=3, text=[tags["original_date"]]))
    id3.add(TCON(encoding=3, text=tags["genres"]))
    id3.add(TMED(encoding=3, text=[tags["media"]]))
    id3.add(TPUB(encoding=3, text=[tags["label"]]))
    id3.add(TSRC(encoding=3, text=[tags["isrc"]]))
    id3.add(TCOM(encoding=3, text=[tags["composer"]]))
    id3.add(TEXT(encoding=3, text=[tags["lyricist"]]))
    id3.add(TIPL(encoding=3, people=[["producer", tags["producer"]]]))
    id3.add(TCMP(encoding=3, text=["1"]))
    text_frames = {
        "MusicBrainz Album Status": [tags["release_status"]],
        "MusicBrainz Album Release Country": [tags["release_country"]],
        "MusicBrainz Album Type": tags["release_types"],
        "CATALOGNUMBER": [tags["catalog_number"]],
        "BARCODE": [tags["barcode"]],
        "MusicBrainz Release Group Id": [tags["musicbrainz_release_group_id"]],
        "MusicBrainz Album Id": [tags["musicbrainz_release_id"]],
        "MusicBrainz Release Track Id": [tags["musicbrainz_release_track_id"]],
        "MusicBrainz Artist Id": tags["musicbrainz_artist_ids"],
        "MusicBrainz Album Artist Id": tags["musicbrainz_album_artist_ids"],
        "WORK": [tags["work"]],
        "MusicBrainz Work Id": [tags["musicbrainz_work_id"]],
        "PRODUCER": [tags["producer"]],
        "Acoustid Id": [tags["acoustid_id"]],
        "Acoustid Fingerprint": [tags["acoustid_fingerprint"]],
        "CUSTOM_KEEP": ["opaque local value"],
    }
    for description, values in text_frames.items():
        id3.add(TXXX(encoding=3, desc=description, text=values))
    id3.add(UFID(owner=_MB_UFID_OWNER, data=tags["musicbrainz_recording_id"].encode()))
    id3.add(
        APIC(
            encoding=3, mime="image/png", type=3, desc="Front cover", data=_cover_png()
        )
    )
    return id3


def _write_management_mp3(path: Path) -> None:
    _silence(path, "libmp3lame", ["-b:a", "192k"])
    _id3_management_tags().save(path, v2_version=4)


def _write_management_mp3_v23(path: Path) -> None:
    _silence(path, "libmp3lame", ["-b:a", "192k"])
    _id3_management_tags().save(path, v2_version=3, v23_sep="; ")


def _write_management_wav(path: Path) -> None:
    _silence(path, "pcm_s16le", [])
    audio = WAVE(path)
    audio.add_tags()
    for frame in _id3_management_tags().values():
        audio.tags.add(frame)
    audio.save()


def _write_management_riff_wav(path: Path) -> None:
    """Author a pure RIFF INFO fixture without using the application adapter."""
    _silence(path, "pcm_s16le", [])
    source = path.read_bytes()
    if len(source) < 12 or source[:4] != b"RIFF" or source[8:12] != b"WAVE":
        raise RuntimeError("ffmpeg did not create RIFF/WAVE audio")

    output = bytearray(b"RIFF\x00\x00\x00\x00WAVE")
    position = 12
    while position + 8 <= len(source):
        chunk_size = struct.unpack_from("<I", source, position + 4)[0]
        chunk_end = position + 8 + chunk_size + (chunk_size & 1)
        if chunk_end > len(source):
            raise RuntimeError("ffmpeg created an invalid RIFF chunk table")
        is_info = (
            source[position : position + 4] == b"LIST"
            and chunk_size >= 4
            and source[position + 8 : position + 12] == b"INFO"
        )
        if not is_info:
            output.extend(source[position:chunk_end])
        position = chunk_end
    output.extend(source[position:])

    info_values = {
        "INAM": "RIFF Management Track",
        "IART": "Alpha feat. Beta",
        "IPRD": "RIFF Management Album",
        "ITRK": "2",
        "ICRD": "2024-03-02",
        "IGNR": "Electronic",
        "IMED": "Digital Media",
        "IMUS": "Example Composer",
        "IPRO": "Example Producer",
        "XTRA": "opaque local value",
    }
    info = bytearray(b"INFO")
    for key, value in info_values.items():
        encoded = value.encode("utf-8") + b"\x00"
        info.extend(key.encode("ascii"))
        info.extend(struct.pack("<I", len(encoded)))
        info.extend(encoded)
        if len(encoded) & 1:
            info.extend(b"\x00")
    output.extend(b"LIST")
    output.extend(struct.pack("<I", len(info)))
    output.extend(info)
    if len(info) & 1:
        output.extend(b"\x00")
    struct.pack_into("<I", output, 4, len(output) - 8)
    path.write_bytes(output)


def _write_management_m4a(path: Path) -> None:
    tags = _MANAGEMENT_TAGS
    _silence(path, "aac", ["-b:a", "128k"])
    audio = MP4(path)
    audio["\xa9nam"] = [tags["title"]]
    audio["\xa9ART"] = [tags["artist"]]
    audio[f"{_MP4_PREFIX}ARTISTS"] = [value.encode() for value in tags["artists"]]
    audio["\xa9alb"] = [tags["album"]]
    audio["sonm"] = [tags["title_sort"]]
    audio["soal"] = [tags["album_sort"]]
    audio["aART"] = [tags["album_artist"]]
    audio["soar"] = ["Alpha, The", "Beta, The"]
    audio["soaa"] = ["Alpha, The"]
    audio["trkn"] = [(tags["track_number"], tags["total_tracks"])]
    audio["disk"] = [(tags["disc_number"], tags["total_discs"])]
    audio["\xa9day"] = [tags["date"]]
    audio["\xa9gen"] = tags["genres"]
    audio["cpil"] = True
    audio["stik"] = [1]
    audio["covr"] = [MP4Cover(_cover_png(), imageformat=MP4Cover.FORMAT_PNG)]
    freeform = {
        "DISCSUBTITLE": [tags["disc_subtitle"]],
        "ORIGINALDATE": [tags["original_date"]],
        "MusicBrainz Album Status": [tags["release_status"]],
        "MusicBrainz Album Release Country": [tags["release_country"]],
        "MusicBrainz Album Type": tags["release_types"],
        "MEDIA": [tags["media"]],
        "LABEL": [tags["label"]],
        "CATALOGNUMBER": [tags["catalog_number"]],
        "BARCODE": [tags["barcode"]],
        "ISRC": [tags["isrc"]],
        "MusicBrainz Release Group Id": [tags["musicbrainz_release_group_id"]],
        "MusicBrainz Album Id": [tags["musicbrainz_release_id"]],
        "MusicBrainz Track Id": [tags["musicbrainz_recording_id"]],
        "MusicBrainz Release Track Id": [tags["musicbrainz_release_track_id"]],
        "MusicBrainz Artist Id": tags["musicbrainz_artist_ids"],
        "MusicBrainz Album Artist Id": tags["musicbrainz_album_artist_ids"],
        "MusicBrainz Work Id": [tags["musicbrainz_work_id"]],
        "LYRICIST": [tags["lyricist"]],
        "PRODUCER": [tags["producer"]],
        "Acoustid Id": [tags["acoustid_id"]],
        "Acoustid Fingerprint": [tags["acoustid_fingerprint"]],
        "CUSTOM_KEEP": ["opaque local value"],
    }
    for name, values in freeform.items():
        audio[f"{_MP4_PREFIX}{name}"] = [value.encode() for value in values]
    audio["\xa9wrk"] = [tags["work"]]
    audio.save()


def _write_management_aac(path: Path) -> None:
    _silence(path, "aac", ["-b:a", "128k", "-f", "adts"])
    ape = APEv2()
    tags = _MANAGEMENT_TAGS
    values = {
        key: value
        for key, value in _vorbis_management_pairs()
        if key not in {"TITLE", "ARTIST", "ALBUM", "TRACKNUMBER", "DISCNUMBER"}
    }
    values.update(
        {
            "Title": [tags["title"]],
            "Artist": [tags["artist"]],
            "Artists": tags["artists"],
            "Album": [tags["album"]],
            "Album Artist": [tags["album_artist"]],
            "Track": [f'{tags["track_number"]}/{tags["total_tracks"]}'],
            "Disc": [f'{tags["disc_number"]}/{tags["total_discs"]}'],
            "Genre": tags["genres"],
            "Barcode": [tags["barcode"]],
            "Arranger": ["Example Arranger"],
            "MixArtist": ["Example Remixer"],
        }
    )
    for key, tag_values in values.items():
        ape[key] = "\x00".join(tag_values)
    ape["Cover Art (Front)"] = APEBinaryValue(b"cover.png\x00" + _cover_png())
    ape.save(path)


def _asf_picture() -> bytes:
    mime = "image/png\x00".encode("utf-16-le")
    description = "Front cover\x00".encode("utf-16-le")
    data = _cover_png()
    return bytes([3]) + struct.pack("<I", len(data)) + mime + description + data


def _write_management_wma(path: Path) -> None:
    tags = _MANAGEMENT_TAGS
    _silence(path, "wmav2", ["-b:a", "128k"])
    audio = ASF(path)
    values = {
        "Title": [tags["title"]],
        "Author": [tags["artist"]],
        "WM/ARTISTS": tags["artists"],
        "WM/AlbumTitle": [tags["album"]],
        "WM/TitleSortOrder": [tags["title_sort"]],
        "WM/AlbumSortOrder": [tags["album_sort"]],
        "WM/AlbumArtist": [tags["album_artist"]],
        "WM/ArtistSortOrder": ["Alpha, The", "Beta, The"],
        "WM/AlbumArtistSortOrder": ["Alpha, The"],
        "WM/TrackNumber": [str(tags["track_number"])],
        "WM/TrackTotal": [str(tags["total_tracks"])],
        "WM/PartOfSet": [f'{tags["disc_number"]}/{tags["total_discs"]}'],
        "WM/Year": [tags["date"]],
        "WM/OriginalReleaseYear": [tags["original_date"]],
        "WM/Genre": tags["genres"],
        "MusicBrainz/Album Status": [tags["release_status"]],
        "MusicBrainz/Album Release Country": [tags["release_country"]],
        "MusicBrainz/Album Type": tags["release_types"],
        "WM/Media": [tags["media"]],
        "WM/IsCompilation": ["1"],
        "WM/Publisher": [tags["label"]],
        "WM/CatalogNo": [tags["catalog_number"]],
        "WM/Barcode": [tags["barcode"]],
        "WM/ISRC": [tags["isrc"]],
        "MusicBrainz/Release Group Id": [tags["musicbrainz_release_group_id"]],
        "MusicBrainz/Album Id": [tags["musicbrainz_release_id"]],
        "MusicBrainz/Track Id": [tags["musicbrainz_recording_id"]],
        "MusicBrainz/Release Track Id": [tags["musicbrainz_release_track_id"]],
        "MusicBrainz/Artist Id": tags["musicbrainz_artist_ids"],
        "MusicBrainz/Album Artist Id": tags["musicbrainz_album_artist_ids"],
        "WM/Work": [tags["work"]],
        "MusicBrainz/Work Id": [tags["musicbrainz_work_id"]],
        "WM/Composer": [tags["composer"]],
        "WM/Writer": [tags["lyricist"]],
        "WM/Producer": [tags["producer"]],
        "Acoustid/Id": [tags["acoustid_id"]],
        "Acoustid/Fingerprint": [tags["acoustid_fingerprint"]],
        "CUSTOM_KEEP": ["opaque local value"],
    }
    for key, value in values.items():
        audio[key] = value
    audio["WM/Picture"] = [ASFByteArrayAttribute(_asf_picture())]
    audio.save()


def _vorbis_pairs(tags: dict):
    pairs = [
        ("TITLE", [tags["title"]]),
        ("ARTIST", [tags["artist"]]),
        ("ALBUM", [tags["album"]]),
        ("TRACKNUMBER", [str(tags["track_number"])]),
        ("DISCNUMBER", [str(tags.get("disc_number", 1))]),
        ("COMPILATION", ["1" if tags.get("compilation") else "0"]),
    ]
    if tags.get("album_artist"):
        pairs.append(("ALBUMARTIST", [tags["album_artist"]]))
    if tags.get("year"):
        pairs.append(("DATE", [str(tags["year"])]))
    if tags.get("genre"):
        pairs.append(("GENRE", [tags["genre"]]))
    for field, key in _VORBIS.items():
        if tags.get(field):
            pairs.append((key, [tags[field]]))
    return pairs


# (filename, writer, tags). Covers: well-tagged FLAC/MP3/M4A albums, a VA
# compilation, no-tags, only-release-MBID (not release-group), and CJK names.
_SPECS: list[tuple[str, str, dict]] = [
    (
        "flac_full_01.flac",
        "flac",
        {
            "title": "Airbag",
            "artist": "Radiohead",
            "album": "OK Computer",
            "album_artist": "Radiohead",
            "track_number": 1,
            "disc_number": 1,
            "year": 1997,
            "genre": "Alternative Rock",
            "musicbrainz_release_group_id": "b1392450-e666-3926-a536-22c65f834433",
            "musicbrainz_release_id": "0da3b3e3-1111-4444-8888-aaaaaaaaaaaa",
            "musicbrainz_recording_id": "rec-airbag-0001",
            "musicbrainz_artist_id": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
            "acoustid_id": "ac-airbag-0001",
        },
    ),
    (
        "flac_full_02.flac",
        "flac",
        {
            "title": "Paranoid Android",
            "artist": "Radiohead",
            "album": "OK Computer",
            "album_artist": "Radiohead",
            "track_number": 2,
            "year": 1997,
            "musicbrainz_release_group_id": "b1392450-e666-3926-a536-22c65f834433",
            "musicbrainz_recording_id": "rec-paranoid-0002",
            "musicbrainz_artist_id": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
        },
    ),
    (
        "mp3_full_01.mp3",
        "mp3",
        {
            "title": "One",
            "artist": "U2",
            "album": "Achtung Baby",
            "album_artist": "U2",
            "track_number": 3,
            "year": 1991,
            "genre": "Rock",
            "musicbrainz_release_group_id": "rg-achtung-0001",
            "musicbrainz_release_id": "rel-achtung-0001",
            "musicbrainz_recording_id": "rec-one-0003",
            "musicbrainz_artist_id": "art-u2-0001",
        },
    ),
    (
        "m4a_full_01.m4a",
        "m4a",
        {
            "title": "Teardrop",
            "artist": "Massive Attack",
            "album": "Mezzanine",
            "album_artist": "Massive Attack",
            "track_number": 4,
            "year": 1998,
            "musicbrainz_release_group_id": "rg-mezzanine-0001",
            "musicbrainz_recording_id": "rec-teardrop-0004",
            "musicbrainz_artist_id": "art-massive-0001",
        },
    ),
    (
        "flac_compilation_01.flac",
        "flac",
        {
            "title": "Song A",
            "artist": "Artist One",
            "album": "Now Thats Music",
            "album_artist": "Various Artists",
            "track_number": 1,
            "year": 2001,
            "compilation": True,
            "musicbrainz_release_group_id": "rg-comp-0001",
            "musicbrainz_recording_id": "rec-songa-0001",
            "musicbrainz_artist_id": "art-one-0001",
        },
    ),
    (
        "flac_only_release_mbid.flac",
        "flac",
        {
            "title": "Edition Track",
            "artist": "Some Band",
            "album": "Some Album",
            "album_artist": "Some Band",
            "track_number": 1,
            "year": 2010,
            "musicbrainz_release_id": "rel-only-0001",  # no release-group on purpose
            "musicbrainz_recording_id": "rec-edition-0001",
        },
    ),
    (
        "flac_cjk_01.flac",
        "flac",
        {
            "title": "桃源へ",
            "artist": "ユキ",
            "album": "望厚",
            "album_artist": "ユキ",
            "track_number": 1,
            "year": 2015,
            "musicbrainz_release_group_id": "rg-cjk-0001",
            "musicbrainz_recording_id": "rec-cjk-0001",
        },
    ),
    (
        "flac_no_tags.flac",
        "flac",
        {
            "title": "",
            "artist": "",
            "album": "",
            "track_number": 0,
        },
    ),
]

_WRITERS = {"flac": _write_flac, "mp3": _write_mp3, "m4a": _write_m4a}


def generate() -> None:
    for suffix in ("flac", "mp3", "m4a", "ogg", "opus", "aac", "wav", "wma"):
        for existing in FIXTURES.glob(f"*.{suffix}"):
            existing.unlink()
    for name, fmt, tags in _SPECS:
        _WRITERS[fmt](FIXTURES / name, tags)
    _write_management_flac(FIXTURES / "management_full.flac")
    _write_management_mp3(FIXTURES / "management_full.mp3")
    _write_management_mp3_v23(FIXTURES / "management_full_v23.mp3")
    _write_management_ogg(FIXTURES / "management_full.ogg", opus=False)
    _write_management_ogg(FIXTURES / "management_full.opus", opus=True)
    _write_management_m4a(FIXTURES / "management_full.m4a")
    _write_management_aac(FIXTURES / "management_full.aac")
    _write_management_wav(FIXTURES / "management_full.wav")
    _write_management_riff_wav(FIXTURES / "management_full_riff.wav")
    _write_management_wma(FIXTURES / "management_full.wma")
    print(f"Generated {len(_SPECS) + 10} fixtures in {FIXTURES}")


if __name__ == "__main__":
    generate()
