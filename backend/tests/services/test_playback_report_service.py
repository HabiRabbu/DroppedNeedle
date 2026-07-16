from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.compat.playback_report_service import PlaybackReportService


@pytest.mark.asyncio
async def test_playback_transitions_presence_and_scrobbles_once_at_threshold():
    adapter = AsyncMock()
    view = AsyncMock()
    view.get_track.return_value = SimpleNamespace(duration_seconds=200)
    service = PlaybackReportService(adapter, view)

    common = {
        "user_id": "alice",
        "user_name": "Alice",
        "client": "client",
        "ignore_scrobble": False,
    }
    await service.report("song", position_ms=0, state="starting", **common)
    await service.report("song", position_ms=50_000, state="paused", **common)
    await service.report("song", position_ms=100_000, state="stopped", **common)
    await service.report("song", position_ms=100_000, state="stopped", **common)

    adapter.now_playing.assert_awaited_once()
    adapter.progress.assert_awaited_once()
    assert adapter.progress.await_args.kwargs["is_paused"] is True
    adapter.clear_presence.assert_awaited()
    adapter.scrobble.assert_awaited_once()


@pytest.mark.asyncio
async def test_playback_ignore_scrobble_and_bounded_session_state():
    adapter = AsyncMock()
    view = AsyncMock()
    view.get_track.return_value = SimpleNamespace(duration_seconds=10)
    service = PlaybackReportService(adapter, view, max_sessions=2)

    for file_id in ("one", "two", "three"):
        await service.report(
            file_id,
            user_id="alice",
            user_name="Alice",
            client="client",
            position_ms=10_000,
            state="stopped",
            ignore_scrobble=True,
        )

    assert service.session_count == 2
    adapter.scrobble.assert_not_awaited()
    assert adapter.clear_presence.await_count == 3
