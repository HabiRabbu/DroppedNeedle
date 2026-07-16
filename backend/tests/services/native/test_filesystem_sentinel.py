import os
from pathlib import Path

import pytest

from tests.services.native.filesystem_sentinel import FilesystemSentinel


@pytest.fixture
def audio_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "music"
    root.mkdir()
    (root / "track.flac").write_bytes(b"fLaC-fixture")
    return root


@pytest.mark.parametrize(
    "workflow",
    ["scan", "identification", "review", "repair", "migration"],
)
def test_sentinel_accepts_read_only_workflows(
    audio_fixture: Path, workflow: str
) -> None:
    sentinel = FilesystemSentinel.capture(audio_fixture)

    assert (audio_fixture / "track.flac").read_bytes().startswith(b"fLaC")
    assert workflow
    sentinel.assert_unchanged(audio_fixture)


def test_sentinel_detects_audio_content_mutation(audio_fixture: Path) -> None:
    sentinel = FilesystemSentinel.capture(audio_fixture)
    (audio_fixture / "track.flac").write_bytes(b"changed")

    with pytest.raises(AssertionError, match="audio filesystem changed"):
        sentinel.assert_unchanged(audio_fixture)


def test_sentinel_detects_audio_mtime_mutation(audio_fixture: Path) -> None:
    sentinel = FilesystemSentinel.capture(audio_fixture)
    path = audio_fixture / "track.flac"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    with pytest.raises(AssertionError, match="audio filesystem changed"):
        sentinel.assert_unchanged(audio_fixture)
