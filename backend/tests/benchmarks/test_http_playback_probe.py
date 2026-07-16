import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.native_library_store import NativeLibraryStore
from tests.benchmarks.http_playback_probe import AuthenticatedHTTPPlaybackProbe


@pytest.mark.asyncio
async def test_probe_uses_authenticated_http_range_and_target_sqlite(
    tmp_path: Path,
) -> None:
    database = tmp_path / "target.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE auth_users(id TEXT PRIMARY KEY)")
    audio = tmp_path / "playback.flac"
    audio.write_bytes(b"fLaC" + b"\0" * (128 * 1024))
    store = NativeLibraryStore(database, threading.Lock())

    async with AuthenticatedHTTPPlaybackProbe(store, tmp_path, audio) as probe:
        latency = await probe.sample()
        evidence = probe.evidence()

    assert latency > 0
    assert evidence["authentication_rejections"] == 1
    assert evidence["status_codes"] == [206]
    assert evidence["content_ranges"] == ["bytes 0-65535/131076"]
    assert evidence["bytes_received"] == 2 * 65_536
