import os
from pathlib import Path

import pytest

from services.compat.native_lyrics_service import NativeLyricsService


class _LocalFiles:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def resolve_validated_path(self, file_id: str) -> Path:
        assert file_id == "track-1"
        return self.path


@pytest.mark.asyncio
async def test_reads_sorts_and_bounds_lrc_sidecar_off_thread(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"not-read-when-sidecar-exists")
    audio.with_suffix(".lrc").write_text(
        "[00:02.50]second\n[00:01.005]first\n[00:02.50]layer",
        encoding="utf-8",
    )

    result = await NativeLyricsService(_LocalFiles(audio)).get("track-1")

    assert result is not None
    assert result.synced is True
    assert [(line.start_ms, line.value) for line in result.lines] == [
        (1005, "first"),
        (2500, "second"),
        (2500, "layer"),
    ]


@pytest.mark.asyncio
async def test_plain_lrc_is_unsynced_and_cache_tracks_sidecar_identity(tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"not-read-when-sidecar-exists")
    sidecar = audio.with_suffix(".lrc")
    sidecar.write_text("one\ntwo", encoding="utf-8")
    service = NativeLyricsService(_LocalFiles(audio))

    first = await service.get("track-1")
    sidecar.write_text("changed", encoding="utf-8")
    os.utime(sidecar, ns=(sidecar.stat().st_atime_ns, sidecar.stat().st_mtime_ns + 1))
    second = await service.get("track-1")

    assert first is not None and first.synced is False
    assert [line.value for line in first.lines] == ["one", "two"]
    assert second is not None
    assert [line.value for line in second.lines] == ["changed"]


@pytest.mark.asyncio
async def test_oversized_sidecar_degrades_to_absence(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"audio")
    audio.with_suffix(".lrc").write_bytes(b"x" * (1_048_576 + 1))

    assert await NativeLyricsService(_LocalFiles(audio)).get("track-1") is None
