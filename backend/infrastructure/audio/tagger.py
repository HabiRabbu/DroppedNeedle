"""AudioTagger - the mutagen seam.

Reads/writes tag metadata and cover art across the three formats we care about:
MP3 (ID3v2), FLAC/OGG (Vorbis comments), and M4A (MP4 atoms). The MusicBrainz
fields use the Picard tag names; the per-format mapping lives in the ``_*_MB``
tables below and is the single source of truth for both read and write.

This is the mock seam for the scanner: tests mock ``AudioTagger`` (or
``mutagen.File``), never mutagen's per-format classes directly.
"""

import logging
from pathlib import Path
from typing import Any

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    TALB,
    TCMP,
    TCON,
    TDOR,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TSO2,
    TSOA,
    TSOP,
    TSOT,
    TSST,
    TXXX,
    UFID,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from models.audio import AudioInfo, AudioTag

logger = logging.getLogger(__name__)

# Picard MusicBrainz tag names per format. Keys are AudioTag attribute names.
# NOTE: the *Recording* MBID (musicbrainz_recording_id) is NOT the "Release Track
# Id" - it is Vorbis MUSICBRAINZ_TRACKID / ID3 UFID:http://musicbrainz.org / MP4
# "MusicBrainz Track Id". (ID3 stores it in a UFID frame, handled separately below,
# so it is intentionally absent from _ID3_MB.)
_MB_UFID_OWNER = "http://musicbrainz.org"
_VORBIS_MB = {
    "musicbrainz_release_group_id": "MUSICBRAINZ_RELEASEGROUPID",
    "musicbrainz_release_id": "MUSICBRAINZ_ALBUMID",
    "musicbrainz_recording_id": "MUSICBRAINZ_TRACKID",
    "musicbrainz_artist_id": "MUSICBRAINZ_ARTISTID",
    "musicbrainz_album_artist_id": "MUSICBRAINZ_ALBUMARTISTID",
    "acoustid_id": "ACOUSTID_ID",
}
_ID3_MB = {
    "musicbrainz_release_group_id": "MusicBrainz Release Group Id",
    "musicbrainz_release_id": "MusicBrainz Album Id",
    "musicbrainz_artist_id": "MusicBrainz Artist Id",
    "musicbrainz_album_artist_id": "MusicBrainz Album Artist Id",
    "acoustid_id": "Acoustid Id",
}
_MP4_PREFIX = "----:com.apple.iTunes:"
_MP4_MB = {
    "musicbrainz_release_group_id": f"{_MP4_PREFIX}MusicBrainz Release Group Id",
    "musicbrainz_release_id": f"{_MP4_PREFIX}MusicBrainz Album Id",
    "musicbrainz_recording_id": f"{_MP4_PREFIX}MusicBrainz Track Id",
    "musicbrainz_artist_id": f"{_MP4_PREFIX}MusicBrainz Artist Id",
    "musicbrainz_album_artist_id": f"{_MP4_PREFIX}MusicBrainz Album Artist Id",
    "acoustid_id": f"{_MP4_PREFIX}Acoustid Id",
}

# The release-level MusicBrainz IDs the download request owns authoritatively.
# ``write_album_identity`` stamps only these (plus album/album-artist/year) so an
# import never rewrites the file's own descriptive tags - title, artist, genre,
# and the recording/artist/acoustid IDs already present stay byte-for-byte.
_OWNED_MB_FIELDS = (
    "musicbrainz_release_group_id",
    "musicbrainz_release_id",
    "musicbrainz_album_artist_id",
)

_SUFFIX_FORMATS = {
    ".flac": "flac",
    ".mp3": "mp3",
    ".ogg": "ogg",
    ".oga": "ogg",
    ".opus": "opus",
    ".m4a": "m4a",
    ".m4b": "m4a",
    ".mp4": "m4a",
}

# Only these report a meaningful bit depth. MP4Info.bits_per_sample is 16 even
# for lossy AAC, so bit_depth must be suppressed for lossy formats.
_LOSSLESS_FORMATS = {"flac"}


def _first(value: Any) -> str | None:
    """First element of a mutagen value list, coerced to ``str``."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    text = str(value).strip()
    return text or None


def _join_all(value: Any, sep: str = "; ") -> str | None:
    """Every value of a (commonly multi-valued) mutagen field, de-duplicated in
    order and joined with ``sep``.

    Genre lives as a list of Vorbis ``GENRE`` fields, an MP4 ``©gen`` list, or an
    ID3 ``TCON`` frame whose text is itself a list (multi-value frames stringify
    with NUL joins). Reading only the first value (``_first``) silently hides the
    rest from our DB/UI, so genre uses this instead to surface the truth."""
    if value is None:
        return None
    raw = getattr(value, "text", value)  # an ID3 frame -> its text list
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        for part in str(item).split("\x00"):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                out.append(part)
    return sep.join(out) or None


def _leading_int(value: Any) -> int | None:
    """Parse the leading integer of a ``"5"`` or ``"5/12"`` style field."""
    text = _first(value)
    if text is None:
        return None
    head = text.split("/", 1)[0].strip()
    try:
        return int(head)
    except ValueError:
        return None


def _year(value: Any) -> int | None:
    text = _first(value)
    if text is None:
        return None
    try:
        return int(text[:4])
    except ValueError:
        return None


def _float_tag(value: Any, *, positive: bool = False) -> float | None:
    text = _first(value)
    if text is None:
        return None
    normalized = text.lower().removesuffix("db").strip()
    try:
        result = float(normalized)
    except ValueError:
        return None
    if positive and result < 0:
        return None
    return result


class AudioTagger:
    """Format-dispatching wrapper over mutagen. No state - safe as a singleton."""

    @staticmethod
    def _open(path: Path) -> Any:
        """Load via mutagen, normalising both the ``None`` and corrupt-file
        (``MutagenError``) cases into a single ``ValueError``."""
        try:
            audio = mutagen.File(path)
        except mutagen.MutagenError as exc:
            raise ValueError(f"Unsupported or unreadable audio file: {path}") from exc
        if audio is None:
            raise ValueError(f"Unsupported or unreadable audio file: {path}")
        return audio

    def read_tags(self, path: Path) -> tuple[AudioTag, AudioInfo]:
        """Read tags + technical info. Raises ``ValueError`` on unreadable files."""
        audio = self._open(path)
        fmt = _SUFFIX_FORMATS.get(Path(path).suffix.lower(), "")
        if isinstance(audio, MP4):
            tag = self._read_mp4(audio)
        elif isinstance(audio, MP3):
            tag = self._read_id3(audio)
        else:
            tag = self._read_vorbis(audio)
        info = self._read_info(audio, Path(path), fmt)
        return tag, info

    def write_mb_tags(self, path: Path, tag: AudioTag) -> None:
        """Write the full ``AudioTag`` (descriptive + MusicBrainz fields)."""
        audio = self._open(path)
        if isinstance(audio, MP4):
            self._write_mp4(audio, tag)
        elif isinstance(audio, MP3):
            self._write_id3(audio, tag)
        else:
            self._write_vorbis(audio, tag)
        audio.save()

    def write_album_identity(self, path: Path, tag: AudioTag) -> None:
        """Stamp only the request-owned album identity - album, album artist, year
        and the release-level MusicBrainz IDs (``_OWNED_MB_FIELDS``) - leaving every
        other existing tag untouched.

        The import path uses this instead of ``write_mb_tags`` so re-saving a
        download never round-trips the file's own descriptive tags (title, artist,
        genre, the recording/artist IDs) through our single-value model, which would
        flatten a multi-value genre or artist to its first value."""
        audio = self._open(path)
        if isinstance(audio, MP4):
            if audio.tags is None:
                audio.add_tags()
            tags = audio.tags
            tags["\xa9alb"] = [tag.album]
            if tag.album_artist is not None:
                tags["aART"] = [tag.album_artist]
            if tag.year is not None:
                tags["\xa9day"] = [str(tag.year)]
            for field in _OWNED_MB_FIELDS:
                value = getattr(tag, field)
                if value:
                    tags[_MP4_MB[field]] = [value.encode("utf-8")]
        elif isinstance(audio, MP3):
            if audio.tags is None:
                audio.add_tags()
            tags = audio.tags
            tags.setall("TALB", [TALB(encoding=3, text=[tag.album])])
            if tag.album_artist is not None:
                tags.setall("TPE2", [TPE2(encoding=3, text=[tag.album_artist])])
            if tag.year is not None:
                tags.setall("TDRC", [TDRC(encoding=3, text=[str(tag.year)])])
            for field in _OWNED_MB_FIELDS:
                value = getattr(tag, field)
                if value:
                    desc = _ID3_MB[field]
                    tags.setall(f"TXXX:{desc}", [TXXX(encoding=3, desc=desc, text=[value])])
        else:
            audio["ALBUM"] = tag.album
            if tag.album_artist is not None:
                audio["ALBUMARTIST"] = tag.album_artist
            if tag.year is not None:
                audio["DATE"] = str(tag.year)
            for field in _OWNED_MB_FIELDS:
                value = getattr(tag, field)
                if value:
                    audio[_VORBIS_MB[field]] = value
        audio.save()

    def read_cover_art(self, path: Path) -> bytes | None:
        try:
            audio = mutagen.File(path)
        except mutagen.MutagenError:
            return None
        if audio is None:
            return None
        if isinstance(audio, MP4):
            covers = audio.tags.get("covr") if audio.tags else None
            return bytes(covers[0]) if covers else None
        if isinstance(audio, FLAC):
            return bytes(audio.pictures[0].data) if audio.pictures else None
        tags = getattr(audio, "tags", None)
        if tags is not None:
            for frame in tags.getall("APIC") if hasattr(tags, "getall") else []:
                return bytes(frame.data)
        return None

    def write_cover_art(self, path: Path, data: bytes) -> None:
        audio = self._open(path)
        if isinstance(audio, MP4):
            if audio.tags is None:
                audio.add_tags()
            audio.tags["covr"] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)]
        elif isinstance(audio, FLAC):
            picture = Picture()
            picture.data = data
            picture.type = 3  # front cover
            picture.mime = "image/jpeg"
            audio.clear_pictures()
            audio.add_picture(picture)
        else:
            if audio.tags is None:
                audio.add_tags()
            audio.tags.setall(
                "APIC", [APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=data)]
            )
        audio.save()

    # -- ID3v2 (MP3) --

    def _read_id3(self, audio: Any) -> AudioTag:
        tags = audio.tags
        if tags is None:
            return AudioTag(title="", artist="", album="", track_number=0)
        return AudioTag(
            title=_first(tags.get("TIT2")) or "",
            artist=_first(tags.get("TPE1")) or "",
            album=_first(tags.get("TALB")) or "",
            album_artist=_first(tags.get("TPE2")),
            track_number=_leading_int(tags.get("TRCK")) or 0,
            disc_number=_leading_int(tags.get("TPOS")) or 1,
            year=_year(tags.get("TDRC")),
            genre=_join_all(tags.get("TCON")),
            compilation=_first(tags.get("TCMP")) == "1",
            title_sort=_first(tags.get("TSOT")),
            artist_sort=_first(tags.get("TSOP")),
            album_sort=_first(tags.get("TSOA")),
            album_artist_sort=_first(tags.get("TSO2")),
            disc_subtitle=_first(tags.get("TSST")),
            original_release_date=_first(tags.get("TDOR")),
            replaygain_track_gain=_float_tag(tags.get("TXXX:REPLAYGAIN_TRACK_GAIN")),
            replaygain_album_gain=_float_tag(tags.get("TXXX:REPLAYGAIN_ALBUM_GAIN")),
            replaygain_track_peak=_float_tag(
                tags.get("TXXX:REPLAYGAIN_TRACK_PEAK"), positive=True
            ),
            replaygain_album_peak=_float_tag(
                tags.get("TXXX:REPLAYGAIN_ALBUM_PEAK"), positive=True
            ),
            **self._read_id3_mb(tags),
        )

    def _read_id3_mb(self, tags: Any) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for field, desc in _ID3_MB.items():
            frame = tags.get(f"TXXX:{desc}")
            out[field] = _first(frame.text) if frame is not None else None
        # The recording MBID is a UFID frame (owner = musicbrainz.org), not a TXXX.
        ufid = tags.get(f"UFID:{_MB_UFID_OWNER}")
        out["musicbrainz_recording_id"] = (
            bytes(ufid.data).decode("utf-8", "ignore").strip() or None if ufid is not None else None
        )
        return out

    def _write_id3(self, audio: Any, tag: AudioTag) -> None:
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        tags.setall("TIT2", [TIT2(encoding=3, text=[tag.title])])
        tags.setall("TPE1", [TPE1(encoding=3, text=[tag.artist])])
        tags.setall("TALB", [TALB(encoding=3, text=[tag.album])])
        if tag.album_artist is not None:
            tags.setall("TPE2", [TPE2(encoding=3, text=[tag.album_artist])])
        tags.setall("TRCK", [TRCK(encoding=3, text=[str(tag.track_number)])])
        tags.setall("TPOS", [TPOS(encoding=3, text=[str(tag.disc_number)])])
        if tag.year is not None:
            tags.setall("TDRC", [TDRC(encoding=3, text=[str(tag.year)])])
        if tag.genre is not None:
            tags.setall("TCON", [TCON(encoding=3, text=[tag.genre])])
        tags.setall("TCMP", [TCMP(encoding=3, text=["1" if tag.compilation else "0"])])
        optional_frames = (
            ("TSOT", TSOT, tag.title_sort),
            ("TSOP", TSOP, tag.artist_sort),
            ("TSOA", TSOA, tag.album_sort),
            ("TSO2", TSO2, tag.album_artist_sort),
            ("TSST", TSST, tag.disc_subtitle),
            ("TDOR", TDOR, tag.original_release_date),
        )
        for key, frame_type, value in optional_frames:
            if value:
                tags.setall(key, [frame_type(encoding=3, text=[value])])
            else:
                tags.delall(key)
        replaygain = (
            ("REPLAYGAIN_TRACK_GAIN", tag.replaygain_track_gain),
            ("REPLAYGAIN_ALBUM_GAIN", tag.replaygain_album_gain),
            ("REPLAYGAIN_TRACK_PEAK", tag.replaygain_track_peak),
            ("REPLAYGAIN_ALBUM_PEAK", tag.replaygain_album_peak),
        )
        for description, value in replaygain:
            key = f"TXXX:{description}"
            if value is not None:
                tags.setall(
                    key,
                    [TXXX(encoding=3, desc=description, text=[str(value)])],
                )
            else:
                tags.delall(key)
        for field, desc in _ID3_MB.items():
            value = getattr(tag, field)
            key = f"TXXX:{desc}"
            if value:
                tags.setall(key, [TXXX(encoding=3, desc=desc, text=[value])])
            elif key in tags:
                tags.delall(key)
        # Recording MBID -> UFID frame (not TXXX).
        ufid_key = f"UFID:{_MB_UFID_OWNER}"
        if tag.musicbrainz_recording_id:
            tags.setall(
                ufid_key,
                [UFID(owner=_MB_UFID_OWNER, data=tag.musicbrainz_recording_id.encode("utf-8"))],
            )
        elif ufid_key in tags:
            tags.delall(ufid_key)

    # -- Vorbis (FLAC/OGG) --

    def _read_vorbis(self, audio: Any) -> AudioTag:
        def g(key: str) -> Any:
            return audio.get(key)

        mb = {field: _first(g(key)) for field, key in _VORBIS_MB.items()}
        return AudioTag(
            title=_first(g("TITLE")) or "",
            artist=_first(g("ARTIST")) or "",
            album=_first(g("ALBUM")) or "",
            album_artist=_first(g("ALBUMARTIST")),
            track_number=_leading_int(g("TRACKNUMBER")) or 0,
            disc_number=_leading_int(g("DISCNUMBER")) or 1,
            year=_year(g("DATE")),
            genre=_join_all(g("GENRE")),
            compilation=_first(g("COMPILATION")) == "1",
            title_sort=_first(g("TITLESORT")),
            artist_sort=_first(g("ARTISTSORT")),
            album_sort=_first(g("ALBUMSORT")),
            album_artist_sort=_first(g("ALBUMARTISTSORT")),
            disc_subtitle=_first(g("DISCSUBTITLE")),
            original_release_date=_first(g("ORIGINALDATE")),
            replaygain_track_gain=_float_tag(g("REPLAYGAIN_TRACK_GAIN")),
            replaygain_album_gain=_float_tag(g("REPLAYGAIN_ALBUM_GAIN")),
            replaygain_track_peak=_float_tag(g("REPLAYGAIN_TRACK_PEAK"), positive=True),
            replaygain_album_peak=_float_tag(g("REPLAYGAIN_ALBUM_PEAK"), positive=True),
            **mb,
        )

    def _write_vorbis(self, audio: Any, tag: AudioTag) -> None:
        audio["TITLE"] = tag.title
        audio["ARTIST"] = tag.artist
        audio["ALBUM"] = tag.album
        if tag.album_artist is not None:
            audio["ALBUMARTIST"] = tag.album_artist
        audio["TRACKNUMBER"] = str(tag.track_number)
        audio["DISCNUMBER"] = str(tag.disc_number)
        if tag.year is not None:
            audio["DATE"] = str(tag.year)
        if tag.genre is not None:
            audio["GENRE"] = tag.genre
        audio["COMPILATION"] = "1" if tag.compilation else "0"
        optional = {
            "TITLESORT": tag.title_sort,
            "ARTISTSORT": tag.artist_sort,
            "ALBUMSORT": tag.album_sort,
            "ALBUMARTISTSORT": tag.album_artist_sort,
            "DISCSUBTITLE": tag.disc_subtitle,
            "ORIGINALDATE": tag.original_release_date,
            "REPLAYGAIN_TRACK_GAIN": tag.replaygain_track_gain,
            "REPLAYGAIN_ALBUM_GAIN": tag.replaygain_album_gain,
            "REPLAYGAIN_TRACK_PEAK": tag.replaygain_track_peak,
            "REPLAYGAIN_ALBUM_PEAK": tag.replaygain_album_peak,
        }
        for key, value in optional.items():
            if value is not None:
                audio[key] = str(value)
            elif key in audio:
                del audio[key]
        for field, key in _VORBIS_MB.items():
            value = getattr(tag, field)
            if value:
                audio[key] = value
            elif key in audio:
                del audio[key]

    # -- MP4 (M4A) --

    def _read_mp4(self, audio: Any) -> AudioTag:
        tags = audio.tags or {}

        def text(key: str) -> str | None:
            return _first(tags.get(key))

        def pair(key: str) -> int | None:
            value = tags.get(key)
            if value and isinstance(value[0], (list, tuple)) and value[0]:
                return int(value[0][0])
            return None

        def freeform(key: str) -> str | None:
            raw = tags.get(key)
            if not raw:
                return None
            value = raw[0]
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace").strip() or None
            return _first(value)

        mb: dict[str, str | None] = {}
        for field, key in _MP4_MB.items():
            raw = tags.get(key)
            mb[field] = bytes(raw[0]).decode("utf-8", "ignore").strip() or None if raw else None
        cpil = tags.get("cpil")  # mutagen returns a plain bool for this atom
        if isinstance(cpil, list):
            cpil = cpil[0] if cpil else False
        return AudioTag(
            title=text("\xa9nam") or "",
            artist=text("\xa9ART") or "",
            album=text("\xa9alb") or "",
            album_artist=text("aART"),
            track_number=pair("trkn") or 0,
            disc_number=pair("disk") or 1,
            year=_year(text("\xa9day")),
            genre=_join_all(tags.get("\xa9gen")),
            compilation=bool(cpil),
            title_sort=text("sonm"),
            artist_sort=text("soar"),
            album_sort=text("soal"),
            album_artist_sort=text("soaa"),
            disc_subtitle=freeform(f"{_MP4_PREFIX}DISCSUBTITLE"),
            original_release_date=freeform(f"{_MP4_PREFIX}ORIGINALDATE"),
            replaygain_track_gain=_float_tag(freeform(f"{_MP4_PREFIX}REPLAYGAIN_TRACK_GAIN")),
            replaygain_album_gain=_float_tag(freeform(f"{_MP4_PREFIX}REPLAYGAIN_ALBUM_GAIN")),
            replaygain_track_peak=_float_tag(
                freeform(f"{_MP4_PREFIX}REPLAYGAIN_TRACK_PEAK"), positive=True
            ),
            replaygain_album_peak=_float_tag(
                freeform(f"{_MP4_PREFIX}REPLAYGAIN_ALBUM_PEAK"), positive=True
            ),
            **mb,
        )

    def _write_mp4(self, audio: Any, tag: AudioTag) -> None:
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        tags["\xa9nam"] = [tag.title]
        tags["\xa9ART"] = [tag.artist]
        tags["\xa9alb"] = [tag.album]
        if tag.album_artist is not None:
            tags["aART"] = [tag.album_artist]
        tags["trkn"] = [(tag.track_number, 0)]
        tags["disk"] = [(tag.disc_number, 0)]
        if tag.year is not None:
            tags["\xa9day"] = [str(tag.year)]
        if tag.genre is not None:
            tags["\xa9gen"] = [tag.genre]
        tags["cpil"] = tag.compilation
        optional = {
            "sonm": tag.title_sort,
            "soar": tag.artist_sort,
            "soal": tag.album_sort,
            "soaa": tag.album_artist_sort,
            f"{_MP4_PREFIX}DISCSUBTITLE": tag.disc_subtitle,
            f"{_MP4_PREFIX}ORIGINALDATE": tag.original_release_date,
        }
        for key, value in optional.items():
            if value is not None:
                tags[key] = [value]
            elif key in tags:
                del tags[key]
        replaygain = {
            f"{_MP4_PREFIX}REPLAYGAIN_TRACK_GAIN": tag.replaygain_track_gain,
            f"{_MP4_PREFIX}REPLAYGAIN_ALBUM_GAIN": tag.replaygain_album_gain,
            f"{_MP4_PREFIX}REPLAYGAIN_TRACK_PEAK": tag.replaygain_track_peak,
            f"{_MP4_PREFIX}REPLAYGAIN_ALBUM_PEAK": tag.replaygain_album_peak,
        }
        for key, value in replaygain.items():
            if value is not None:
                tags[key] = [str(value).encode()]
            elif key in tags:
                del tags[key]
        for field, key in _MP4_MB.items():
            value = getattr(tag, field)
            if value:
                tags[key] = [value.encode("utf-8")]
            elif key in tags:
                del tags[key]

    # -- technical info --

    def _read_info(self, audio: Any, path: Path, fmt: str) -> AudioInfo:
        info = audio.info
        bit_depth = (
            (getattr(info, "bits_per_sample", None) or None)
            if fmt in _LOSSLESS_FORMATS
            else None
        )
        return AudioInfo(
            duration_seconds=float(getattr(info, "length", 0.0) or 0.0),
            bitrate=int(getattr(info, "bitrate", 0) or 0) // 1000,
            sample_rate=int(getattr(info, "sample_rate", 0) or 0),
            channels=int(getattr(info, "channels", 0) or 0),
            file_format=fmt or (path.suffix.lower().lstrip(".") or "unknown"),
            file_size_bytes=path.stat().st_size if path.exists() else 0,
            bit_depth=bit_depth,
        )
