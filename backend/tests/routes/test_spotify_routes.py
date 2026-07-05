"""Route-level tests for the Spotify import background task (PR #108).

``_background_import`` runs fire-and-forget after the import POST returns; these
exercise it directly (no HTTP) and confirm it signals completion over SSE so the
frontend refreshes the imported playlist without a manual reload.
"""

from unittest.mock import AsyncMock

import pytest

from api.v1.routes import spotify as spotify_routes


@pytest.mark.asyncio
async def test_background_import_signals_completion_over_sse(monkeypatch):
    publisher = AsyncMock()
    monkeypatch.setattr(spotify_routes, "get_sse_publisher", lambda: publisher)
    # Auto-link is best-effort; stub the source services so the task reaches the signal.
    for getter in (
        "get_playlist_service",
        "get_jellyfin_library_service",
        "get_local_files_service",
        "get_navidrome_library_service",
        "get_plex_library_service",
    ):
        monkeypatch.setattr(spotify_routes, getter, lambda: AsyncMock())

    svc = AsyncMock()
    await spotify_routes._background_import(svc, "user-1", "spot-1", "int-1", object())

    svc.populate_playlist.assert_awaited_once_with("user-1", "spot-1", "int-1")
    publisher.publish.assert_awaited_once()
    channel, event, data = publisher.publish.await_args.args
    assert channel == "user:user-1"
    assert event == "playlist_imported"
    assert data["playlist_id"] == "int-1"
    assert data["event_id"]  # present so the client can de-dupe replays


@pytest.mark.asyncio
async def test_background_import_does_not_signal_when_populate_fails(monkeypatch):
    publisher = AsyncMock()
    monkeypatch.setattr(spotify_routes, "get_sse_publisher", lambda: publisher)

    svc = AsyncMock()
    svc.populate_playlist = AsyncMock(side_effect=RuntimeError("populate blew up"))

    # Must not raise (fire-and-forget task) and must not claim completion.
    await spotify_routes._background_import(svc, "user-1", "spot-1", "int-1", object())

    publisher.publish.assert_not_awaited()
