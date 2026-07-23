"""Small, deterministic LRC/SYLT conversion helpers."""

from __future__ import annotations

import re

_TIMESTAMP = re.compile(r"\[(\d+):(\d{2}(?:\.\d{1,3})?)\]")


def parse_lrc(value: str) -> tuple[tuple[str, int], ...]:
    entries: list[tuple[str, int]] = []
    for line in value.splitlines():
        matches = tuple(_TIMESTAMP.finditer(line))
        if not matches:
            continue
        text = line[matches[-1].end() :]
        for match in matches:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            if seconds >= 60:
                continue
            milliseconds = minutes * 60_000 + int(round(seconds * 1000))
            entries.append((text, milliseconds))
    return tuple(entries)


def render_lrc(entries: tuple[tuple[str, int], ...]) -> str:
    lines: list[str] = []
    for text, milliseconds in entries:
        minutes, remainder = divmod(max(0, milliseconds), 60_000)
        seconds, fraction = divmod(remainder, 1000)
        lines.append(f"[{minutes:02d}:{seconds:02d}.{fraction:03d}]{text}")
    return "\n".join(lines)


def normalize_lrc(value: str) -> str | None:
    entries = parse_lrc(value)
    return render_lrc(entries) if entries else None
