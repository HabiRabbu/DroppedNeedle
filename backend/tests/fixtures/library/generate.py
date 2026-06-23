"""Generate the committed audio fixtures used by the Phase 3 library tests.

Run from a dev box with ffmpeg installed (``python generate.py``); the produced
files are small (~0.3s silence, a few KB) and committed to the repo, so the
tests themselves only need mutagen to read them — never ffmpeg.

Tags are written with **raw mutagen** (not AudioTagger) on purpose: the tagger
tests must validate against an independent oracle, otherwise a symmetric
read/write bug would hide.

Idempotent: deletes and regenerates the whole set on every run.
"""

import subprocess
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import (
    ID3,
    TALB,
    TCMP,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TXXX,
    UFID,
)
from mutagen.mp4 import MP4

FIXTURES = Path(__file__).resolve().parent

# Picard tag names, mirrored here independently of the app's tagger. The recording
# MBID lives in Vorbis MUSICBRAINZ_TRACKID / ID3 UFID:musicbrainz.org / MP4
# "MusicBrainz Track Id" — NOT the "Release Track Id" tags.
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


def _silence(path: Path, codec: str, extra: list[str]) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "0.3", "-c:a", codec, *extra, str(path),
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
        audio.add(UFID(owner=_MB_UFID_OWNER, data=tags["musicbrainz_recording_id"].encode("utf-8")))
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
    ("flac_full_01.flac", "flac", {
        "title": "Airbag", "artist": "Radiohead", "album": "OK Computer",
        "album_artist": "Radiohead", "track_number": 1, "disc_number": 1,
        "year": 1997, "genre": "Alternative Rock",
        "musicbrainz_release_group_id": "b1392450-e666-3926-a536-22c65f834433",
        "musicbrainz_release_id": "0da3b3e3-1111-4444-8888-aaaaaaaaaaaa",
        "musicbrainz_recording_id": "rec-airbag-0001",
        "musicbrainz_artist_id": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
        "acoustid_id": "ac-airbag-0001",
    }),
    ("flac_full_02.flac", "flac", {
        "title": "Paranoid Android", "artist": "Radiohead", "album": "OK Computer",
        "album_artist": "Radiohead", "track_number": 2, "year": 1997,
        "musicbrainz_release_group_id": "b1392450-e666-3926-a536-22c65f834433",
        "musicbrainz_recording_id": "rec-paranoid-0002",
        "musicbrainz_artist_id": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
    }),
    ("mp3_full_01.mp3", "mp3", {
        "title": "One", "artist": "U2", "album": "Achtung Baby",
        "album_artist": "U2", "track_number": 3, "year": 1991, "genre": "Rock",
        "musicbrainz_release_group_id": "rg-achtung-0001",
        "musicbrainz_release_id": "rel-achtung-0001",
        "musicbrainz_recording_id": "rec-one-0003",
        "musicbrainz_artist_id": "art-u2-0001",
    }),
    ("m4a_full_01.m4a", "m4a", {
        "title": "Teardrop", "artist": "Massive Attack", "album": "Mezzanine",
        "album_artist": "Massive Attack", "track_number": 4, "year": 1998,
        "musicbrainz_release_group_id": "rg-mezzanine-0001",
        "musicbrainz_recording_id": "rec-teardrop-0004",
        "musicbrainz_artist_id": "art-massive-0001",
    }),
    ("flac_compilation_01.flac", "flac", {
        "title": "Song A", "artist": "Artist One", "album": "Now Thats Music",
        "album_artist": "Various Artists", "track_number": 1, "year": 2001,
        "compilation": True,
        "musicbrainz_release_group_id": "rg-comp-0001",
        "musicbrainz_recording_id": "rec-songa-0001",
        "musicbrainz_artist_id": "art-one-0001",
    }),
    ("flac_only_release_mbid.flac", "flac", {
        "title": "Edition Track", "artist": "Some Band", "album": "Some Album",
        "album_artist": "Some Band", "track_number": 1, "year": 2010,
        "musicbrainz_release_id": "rel-only-0001",  # no release-group on purpose
        "musicbrainz_recording_id": "rec-edition-0001",
    }),
    ("flac_cjk_01.flac", "flac", {
        "title": "桃源へ", "artist": "ユキ", "album": "望厚",
        "album_artist": "ユキ", "track_number": 1, "year": 2015,
        "musicbrainz_release_group_id": "rg-cjk-0001",
        "musicbrainz_recording_id": "rec-cjk-0001",
    }),
    ("flac_no_tags.flac", "flac", {
        "title": "", "artist": "", "album": "", "track_number": 0,
    }),
]

_WRITERS = {"flac": _write_flac, "mp3": _write_mp3, "m4a": _write_m4a}


def generate() -> None:
    for existing in (*FIXTURES.glob("*.flac"), *FIXTURES.glob("*.mp3"), *FIXTURES.glob("*.m4a")):
        existing.unlink()
    for name, fmt, tags in _SPECS:
        _WRITERS[fmt](FIXTURES / name, tags)
    print(f"Generated {len(_SPECS)} fixtures in {FIXTURES}")


if __name__ == "__main__":
    generate()
