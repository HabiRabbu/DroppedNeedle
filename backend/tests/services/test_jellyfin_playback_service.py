import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from core.exceptions import ExternalServiceError, PlaybackNotAllowedError
from infrastructure.constants import JELLYFIN_TICKS_PER_SECOND
from services.jellyfin_playback_service import (
    JellyfinPlaybackService,
)


def _make_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_playback_info = AsyncMock(
        return_value={
            "PlaySessionId": "sess-123",
            "MediaSources": [{"SupportsDirectPlay": True, "SupportsDirectStream": True}],
        }
    )
    repo.report_playback_start = AsyncMock()
    repo.report_playback_progress = AsyncMock()
    repo.report_playback_stopped = AsyncMock()
    return repo


@pytest.fixture
def service():
    repo = _make_repo()
    svc = JellyfinPlaybackService(jellyfin_repo=repo)
    return svc, repo


@pytest.mark.asyncio
async def test_start_playback_returns_session_id(service):
    svc, repo = service
    result = await svc.start_playback("item-1")
    assert result == "sess-123"
    repo.report_playback_start.assert_called_once_with(
        "item-1", "sess-123", play_method="DirectPlay"
    )


@pytest.mark.asyncio
async def test_start_playback_raises_on_error_code(service):
    svc, repo = service
    repo.get_playback_info.return_value = {"ErrorCode": "NotAllowed"}

    with pytest.raises(PlaybackNotAllowedError, match="NotAllowed"):
        await svc.start_playback("item-1")


@pytest.mark.asyncio
async def test_start_playback_handles_null_session_id(service):
    svc, repo = service
    repo.get_playback_info.return_value = {"PlaySessionId": None}

    result = await svc.start_playback("item-1")
    assert result == ""


@pytest.mark.asyncio
async def test_report_progress_sends_to_jellyfin(service):
    svc, repo = service
    await svc.report_progress("item-1", "sess-123", 5.0, False)
    expected_ticks = int(5.0 * JELLYFIN_TICKS_PER_SECOND)
    repo.report_playback_progress.assert_called_once_with(
        "item-1", "sess-123", expected_ticks, False
    )


@pytest.mark.asyncio
async def test_report_progress_skips_empty_session(service):
    svc, repo = service
    await svc.report_progress("item-1", "", 5.0, False)
    repo.report_playback_progress.assert_not_called()


@pytest.mark.asyncio
async def test_report_progress_handles_http_failure(service):
    svc, repo = service
    repo.report_playback_progress.side_effect = httpx.ConnectError("network error")
    await svc.report_progress("item-1", "sess-123", 5.0, False)


@pytest.mark.asyncio
async def test_report_progress_handles_external_service_failure(service):
    svc, repo = service
    repo.report_playback_progress.side_effect = ExternalServiceError("server error")
    await svc.report_progress("item-1", "sess-123", 5.0, False)


@pytest.mark.asyncio
async def test_stop_playback_sends_to_jellyfin(service):
    svc, repo = service
    await svc.stop_playback("item-1", "sess-123", 10.0)
    expected_ticks = int(10.0 * JELLYFIN_TICKS_PER_SECOND)
    repo.report_playback_stopped.assert_called_once_with(
        "item-1", "sess-123", expected_ticks
    )


@pytest.mark.asyncio
async def test_stop_playback_skips_empty_session(service):
    svc, repo = service
    await svc.stop_playback("item-1", "", 10.0)
    repo.report_playback_stopped.assert_not_called()


@pytest.mark.asyncio
async def test_stop_playback_handles_failure(service):
    svc, repo = service
    repo.report_playback_stopped.side_effect = httpx.ConnectError("timeout")
    await svc.stop_playback("item-1", "sess-123", 10.0)


@pytest.mark.asyncio
async def test_proxy_head_delegates_to_repo(service):
    svc, repo = service
    from fastapi.responses import Response
    from repositories.navidrome_models import StreamProxyResult

    repo.proxy_head_stream = AsyncMock(
        return_value=StreamProxyResult(
            status_code=200,
            headers={"Content-Type": "audio/flac", "Content-Length": "999"},
            media_type="audio/flac",
        )
    )
    result = await svc.proxy_head("item-1")
    assert isinstance(result, Response)
    repo.proxy_head_stream.assert_awaited_once_with("item-1")


@pytest.mark.asyncio
async def test_proxy_stream_returns_streaming_response(service):
    svc, repo = service
    from fastapi.responses import StreamingResponse
    from repositories.navidrome_models import StreamProxyResult

    async def _chunks():
        yield b"data"

    repo.proxy_get_stream = AsyncMock(
        return_value=StreamProxyResult(
            status_code=200,
            headers={"Content-Type": "audio/flac"},
            media_type="audio/flac",
            body_chunks=_chunks(),
        )
    )
    result = await svc.proxy_stream("item-1", range_header="bytes=0-")
    assert isinstance(result, StreamingResponse)
    repo.proxy_get_stream.assert_awaited_once_with("item-1", range_header="bytes=0-")


@pytest.mark.asyncio
async def test_start_playback_propagates_play_method(service):
    svc, repo = service
    repo.get_playback_info.return_value = {
        "PlaySessionId": "sess-123",
        "MediaSources": [
            {"SupportsDirectPlay": False, "SupportsDirectStream": False, "TranscodingUrl": "/transcode"}
        ],
    }
    await svc.start_playback("item-1")
    repo.report_playback_start.assert_called_once_with(
        "item-1", "sess-123", play_method="Transcode"
    )


class TestPerUserAttribution:
    """Linked users report sessions through their own token; unlinked fall back (issue #138)."""

    def _factory(self, per_user_repo):
        factory = MagicMock()
        factory.resolve_jellyfin = AsyncMock(return_value=per_user_repo)
        return factory

    @pytest.mark.asyncio
    async def test_start_playback_uses_per_user_repo_when_linked(self):
        app_repo = _make_repo()
        per_user = _make_repo()
        svc = JellyfinPlaybackService(jellyfin_repo=app_repo, client_factory=self._factory(per_user))

        result = await svc.start_playback("item-1", user_id="u1")

        assert result == "sess-123"
        per_user.report_playback_start.assert_called_once()
        app_repo.get_playback_info.assert_not_called()
        app_repo.report_playback_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_falls_back_to_app_repo_when_unlinked(self):
        app_repo = _make_repo()
        svc = JellyfinPlaybackService(jellyfin_repo=app_repo, client_factory=self._factory(None))

        await svc.report_progress("item-1", "sess-1", 42.0, is_paused=False, user_id="u1")

        app_repo.report_playback_progress.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_playback_per_user_auth_failure_streams_without_session(self):
        from core.exceptions import JellyfinAuthError

        app_repo = _make_repo()
        per_user = _make_repo()
        per_user.get_playback_info = AsyncMock(side_effect=JellyfinAuthError("revoked"))
        svc = JellyfinPlaybackService(jellyfin_repo=app_repo, client_factory=self._factory(per_user))

        result = await svc.start_playback("item-1", user_id="u1")

        # fail closed: no session reporting, and no misattributed app-level report
        assert result == ""
        app_repo.report_playback_start.assert_not_called()
        per_user.report_playback_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_playback_app_level_auth_failure_still_raises(self):
        from core.exceptions import JellyfinAuthError

        app_repo = _make_repo()
        app_repo.get_playback_info = AsyncMock(side_effect=JellyfinAuthError("bad api key"))
        svc = JellyfinPlaybackService(jellyfin_repo=app_repo)

        with pytest.raises(JellyfinAuthError):
            await svc.start_playback("item-1")
