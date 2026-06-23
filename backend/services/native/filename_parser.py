"""Filename/folder parsing fallback for poorly-tagged files."""

import re
from pathlib import Path

from infrastructure.msgspec_fastapi import AppStruct

_YEAR = re.compile(r"[\(\[]\s*(\d{4})\s*[\)\]]")
_LEADING_TRACK = re.compile(r"^\s*(\d{1,3})\s*[.\-_)]+\s*")
_SPLIT = " - "


class ParsedNames(AppStruct):
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_number: int | None = None
    year: int | None = None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _same(a: str, b: str) -> bool:
    na = _norm(a)
    return bool(na) and na == _norm(b)


def _clean_album_folder(folder: str) -> tuple[str | None, int | None]:
    year_match = _YEAR.search(folder)
    year = int(year_match.group(1)) if year_match else None
    album = _YEAR.sub(" ", folder)
    album = re.sub(r"\s+", " ", album).strip(" -_")
    return (album or None, year)


def parse_names_from_path(path: Path) -> ParsedNames:
    """Best-effort artist/album/title/track/year from a path."""
    stem = path.stem
    parent = path.parent.name
    grandparent = path.parent.parent.name if path.parent.parent != path.parent else ""

    artist = grandparent.strip() or None
    album, year = _clean_album_folder(parent)

    if album and artist:
        if album.lower().startswith(f"{artist.lower()}{_SPLIT}"):
            album = album[len(artist) + len(_SPLIT) :].strip()
        elif _SPLIT in album:
            first, rest = album.split(_SPLIT, 1)
            if _same(first, artist):
                album = rest.strip()

    track: int | None = None
    title = stem
    leading = _LEADING_TRACK.match(title)
    if leading:
        track = int(leading.group(1))
        title = title[leading.end() :].strip()

    if _SPLIT in title:
        parts = [p.strip() for p in title.split(_SPLIT)]
        kept: list[str] = []
        for part in parts:
            if part.isdigit():
                if track is None:
                    track = int(part)
                continue
            if (artist and _same(part, artist)) or (album and _same(part, album)):
                continue
            kept.append(part)
        title = kept[-1] if kept else parts[-1]

    return ParsedNames(
        artist=artist,
        album=album,
        title=(title.strip() or None) if title else None,
        track_number=track,
        year=year,
    )
