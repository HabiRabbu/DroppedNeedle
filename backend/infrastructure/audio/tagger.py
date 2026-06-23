"""AudioTagger — the mutagen seam.

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
from mutagen.id3 import APIC, TALB, TCMP, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX, UFID
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from models.audio import AudioInfo, AudioTag

logger = logging.getLogger(__name__)

# Picard MusicBrainz tag names per format. Keys are AudioTag attribute names.
# NOTE: the *Recording* MBID (musicbrainz_recording_id) is NOT the "Release Track
# Id" — it is Vorbis MUSICBRAINZ_TRACKID / ID3 UFID:http://musicbrainz.org / MP4
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


class AudioTagger:
    """Format-dispatching wrapper over mutagen. No state — safe as a singleton."""

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
            genre=_first(tags.get("TCON")),
            compilation=_first(tags.get("TCMP")) == "1",
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
            genre=_first(g("GENRE")),
            compilation=_first(g("COMPILATION")) == "1",
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
            genre=text("\xa9gen"),
            compilation=bool(cpil),
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
