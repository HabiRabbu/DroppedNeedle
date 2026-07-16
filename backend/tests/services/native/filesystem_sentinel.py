"""Audio immutability assertion shared by Feedback Fixes fixtures."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_AUDIO_SUFFIXES = {
    ".flac",
    ".m4a",
    ".m4b",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
}


@dataclass(frozen=True)
class AudioFileState:
    digest: str
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class FilesystemSentinel:
    files: dict[str, AudioFileState]

    @classmethod
    def capture(cls, root: Path) -> "FilesystemSentinel":
        files: dict[str, AudioFileState] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _AUDIO_SUFFIXES:
                continue
            stat = path.stat()
            files[str(path.relative_to(root))] = AudioFileState(
                digest=hashlib.sha256(path.read_bytes()).hexdigest(),
                mtime_ns=stat.st_mtime_ns,
                size=stat.st_size,
            )
        return cls(files)

    def assert_unchanged(self, root: Path) -> None:
        current = self.capture(root)
        if current != self:
            raise AssertionError(
                f"audio filesystem changed: expected {self.files!r}, got {current.files!r}"
            )
