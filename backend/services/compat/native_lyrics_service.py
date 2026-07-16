"""Bounded native lyrics extraction for the hosted OpenSubsonic API."""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from pathlib import Path

import msgspec
from mutagen import File as MutagenFile
from mutagen import MutagenError

from infrastructure.degradation import try_get_degradation_context
from infrastructure.integration_result import IntegrationResult
from services.local_files_service import LocalFilesService

_MAX_LYRICS_BYTES = 1_048_576
_MAX_LINES = 5_000
_LRC_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_SOURCE = "native_lyrics"


class NativeLyricsLine(msgspec.Struct, frozen=True):
    value: str
    start_ms: int | None = None


class NativeLyrics(msgspec.Struct, frozen=True):
    language: str
    synced: bool
    lines: tuple[NativeLyricsLine, ...]
    source: str


def _record_degradation(message: str) -> None:
    context = try_get_degradation_context()
    if context is not None:
        context.record(IntegrationResult.error(source=_SOURCE, msg=message))


def _plain_lines(value: str) -> tuple[NativeLyricsLine, ...]:
    return tuple(
        NativeLyricsLine(line.rstrip("\r"))
        for line in value.splitlines()[:_MAX_LINES]
    )


def _parse_lrc(value: str) -> tuple[NativeLyricsLine, ...]:
    lines: list[NativeLyricsLine] = []
    for raw_line in value.splitlines():
        timestamps = list(_LRC_TIMESTAMP.finditer(raw_line))
        if not timestamps:
            continue
        lyric = _LRC_TIMESTAMP.sub("", raw_line).strip()
        for timestamp in timestamps:
            minutes = int(timestamp.group(1))
            seconds = int(timestamp.group(2))
            fraction = timestamp.group(3) or "0"
            milliseconds = int(fraction.ljust(3, "0")[:3])
            lines.append(
                NativeLyricsLine(
                    lyric, (minutes * 60 + seconds) * 1000 + milliseconds
                )
            )
            if len(lines) >= _MAX_LINES:
                break
        if len(lines) >= _MAX_LINES:
            break
    return tuple(sorted(lines, key=lambda line: line.start_ms or 0))


def _embedded_lyrics(
    path: Path,
) -> tuple[str, str, tuple[NativeLyricsLine, ...] | None] | None:
    audio = MutagenFile(path)
    tags = getattr(audio, "tags", None) if audio is not None else None
    if tags is None:
        return None
    for key in tags.keys():
        if str(key).upper().startswith("SYLT"):
            frame = tags[key]
            lines = tuple(
                NativeLyricsLine(str(value), int(start))
                for value, start in getattr(frame, "text", ())[:_MAX_LINES]
            )
            if lines:
                return "", str(getattr(frame, "lang", "und") or "und"), lines
        if str(key).upper().startswith("USLT"):
            frame = tags[key]
            return (
                str(getattr(frame, "text", "")),
                str(getattr(frame, "lang", "und") or "und"),
                None,
            )
    for key in ("SYNCEDLYRICS", "SYNCED LYRICS"):
        value = tags.get(key)
        if value:
            if isinstance(value, (list, tuple)):
                value = value[0]
            lines = _parse_lrc(str(value))
            if lines:
                return "", "und", lines
    for key in ("LYRICS", "UNSYNCEDLYRICS", "UNSYNCED LYRICS", "©lyr"):
        value = tags.get(key)
        if value:
            if isinstance(value, (list, tuple)):
                value = value[0]
            return str(value), "und", None
    return None


class NativeLyricsService:
    def __init__(self, local_files: LocalFilesService, *, max_cache_entries: int = 512):
        self._local_files = local_files
        self._max_cache_entries = max_cache_entries
        self._cache: OrderedDict[
            tuple[str, str, int, int, int, int], NativeLyrics | None
        ] = (
            OrderedDict()
        )

    async def get(self, file_id: str) -> NativeLyrics | None:
        path = await self._local_files.resolve_validated_path(file_id)
        sidecar = path.with_suffix(".lrc")
        try:
            file_stat = await asyncio.to_thread(path.stat)
            sidecar_stat = (
                await asyncio.to_thread(sidecar.stat)
                if await asyncio.to_thread(sidecar.is_file)
                else None
            )
        except OSError:
            _record_degradation("Native lyrics source stat failed")
            return None
        cache_key = (
            file_id,
            str(path),
            file_stat.st_mtime_ns,
            file_stat.st_size,
            sidecar_stat.st_mtime_ns if sidecar_stat else 0,
            sidecar_stat.st_size if sidecar_stat else 0,
        )
        if cache_key in self._cache:
            result = self._cache.pop(cache_key)
            self._cache[cache_key] = result
            return result
        try:
            result = await asyncio.to_thread(
                self._read, path, sidecar if sidecar_stat else None, sidecar_stat
            )
        except (OSError, UnicodeError, MutagenError, ValueError):
            _record_degradation("Native lyrics extraction failed")
            result = None
        self._cache[cache_key] = result
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)
        return result

    @staticmethod
    def _read(path: Path, sidecar: Path | None, sidecar_stat) -> NativeLyrics | None:
        if sidecar is not None:
            if sidecar_stat.st_size > _MAX_LYRICS_BYTES:
                raise ValueError("lyrics sidecar exceeds limit")
            value = sidecar.read_text(encoding="utf-8-sig")
            lines = _parse_lrc(value)
            if lines:
                return NativeLyrics("und", True, lines, "sidecar")
            plain = _plain_lines(value)
            return NativeLyrics("und", False, plain, "sidecar") if plain else None
        embedded = _embedded_lyrics(path)
        if embedded is None:
            return None
        value, language, synced_lines = embedded
        if synced_lines:
            return NativeLyrics(language, True, synced_lines, "embedded")
        if len(value.encode("utf-8")) > _MAX_LYRICS_BYTES:
            raise ValueError("embedded lyrics exceed limit")
        lines = _parse_lrc(value)
        if lines:
            return NativeLyrics(language, True, lines, "embedded")
        plain = _plain_lines(value)
        return NativeLyrics(language, False, plain, "embedded") if plain else None
