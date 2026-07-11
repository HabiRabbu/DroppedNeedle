from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.navidrome_playback_service import NavidromePlaybackService


def _make_service(configured: bool = True) -> tuple[NavidromePlaybackService, MagicMock]:
    repo = MagicMock()
    repo.is_configured = MagicMock(return_value=configured)
    repo.build_stream_url = MagicMock(
        return_value="http://navidrome:4533/rest/stream?u=admin&t=tok&s=salt&v=1.16.1&c=droppedneedle&f=json&id=song-1"
    )
    repo.scrobble = AsyncMock(return_value=True)
    service = NavidromePlaybackService(navidrome_repo=repo)
    return service, repo


class TestGetStreamUrl:
    def test_delegates_to_repo(self):
        service, repo = _make_service()
        url = service.get_stream_url("song-1")
        repo.build_stream_url.assert_called_once_with("song-1")
        assert "u=admin" in url
        assert "id=song-1" in url

    def test_base_url_correct(self):
        service, _ = _make_service()
        url = service.get_stream_url("song-1")
        assert url.startswith("http://navidrome:4533/rest/stream?")

    def test_raises_when_not_configured(self):
        service, repo = _make_service(configured=False)
        repo.build_stream_url.side_effect = ValueError("Navidrome is not configured")
        with pytest.raises(ValueError, match="not configured"):
            service.get_stream_url("song-1")


class TestScrobble:
    @pytest.mark.asyncio
    async def test_success(self):
        service, repo = _make_service()
        result = await service.scrobble("song-1")
        assert result is True
        repo.scrobble.assert_awaited_once()
        call_args = repo.scrobble.call_args
        assert call_args.args[0] == "song-1"
        assert call_args.kwargs.get("time_ms") is not None

    @pytest.mark.asyncio
    async def test_failure_returns_false(self):
        service, repo = _make_service()
        repo.scrobble = AsyncMock(side_effect=RuntimeError("network"))
        result = await service.scrobble("song-1")
        assert result is False


class TestPlaybackTrackingBounded:
    @pytest.mark.asyncio
    async def test_now_playing_tracking_is_lru_capped(self):
        from services import navidrome_playback_service as mod

        service, repo = _make_service()
        repo.now_playing = AsyncMock(return_value=True)

        mod._playback_start_times.clear()
        try:
            cap = mod._MAX_TRACKED_PLAYBACKS
            for i in range(cap + 50):
                await service.report_now_playing(f"song-{i}")

            assert len(mod._playback_start_times) == cap
            assert service.get_estimated_position(f"song-{cap + 49}") is not None
            assert service.get_estimated_position("song-0") is None
        finally:
            mod._playback_start_times.clear()


class TestPerUserAttribution:
    """Linked users scrobble through their own repo; unlinked fall back (issue #138)."""

    def _factory(self, per_user_repo):
        factory = MagicMock()
        factory.resolve_navidrome = AsyncMock(return_value=per_user_repo)
        return factory

    @pytest.mark.asyncio
    async def test_scrobble_uses_per_user_repo_when_linked(self):
        service, app_repo = _make_service()
        per_user = MagicMock()
        per_user.scrobble = AsyncMock(return_value=True)
        service._client_factory = self._factory(per_user)

        result = await service.scrobble("song-1", user_id="u1")

        assert result is True
        per_user.scrobble.assert_awaited_once()
        app_repo.scrobble.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scrobble_falls_back_to_app_repo_when_unlinked(self):
        service, app_repo = _make_service()
        service._client_factory = self._factory(None)

        result = await service.scrobble("song-1", user_id="u1")

        assert result is True
        app_repo.scrobble.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scrobble_without_user_id_uses_app_repo(self):
        service, app_repo = _make_service()
        factory = self._factory(MagicMock())
        service._client_factory = factory

        await service.scrobble("song-1")

        factory.resolve_navidrome.assert_not_awaited()
        app_repo.scrobble.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_per_user_auth_failure_fails_closed(self):
        from core.exceptions import NavidromeAuthError

        service, app_repo = _make_service()
        per_user = MagicMock()
        per_user.scrobble = AsyncMock(side_effect=NavidromeAuthError("bad password"))
        service._client_factory = self._factory(per_user)

        result = await service.scrobble("song-1", user_id="u1")

        # fail closed: no silent misattribution via the app account
        assert result is False
        app_repo.scrobble.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_now_playing_uses_per_user_repo_when_linked(self):
        from services import navidrome_playback_service as mod

        service, app_repo = _make_service()
        app_repo.now_playing = AsyncMock(return_value=True)
        per_user = MagicMock()
        per_user.now_playing = AsyncMock(return_value=True)
        service._client_factory = self._factory(per_user)

        mod._playback_start_times.clear()
        try:
            result = await service.report_now_playing("song-1", user_id="u1")
        finally:
            mod._playback_start_times.clear()

        assert result is True
        per_user.now_playing.assert_awaited_once_with("song-1")
        app_repo.now_playing.assert_not_awaited()
