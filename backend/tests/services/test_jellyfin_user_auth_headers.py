"""Jellyfin 10.11+ removed the legacy ``X-Emby-Authorization`` header alongside
``X-Emby-Token`` (issue #151) - ``AuthenticateByName`` must carry the MediaBrowser
identity via the standard ``Authorization`` header."""

import pytest
from unittest.mock import MagicMock

import services.jellyfin_user_auth_service as auth_module
from services.jellyfin_user_auth_service import JellyfinUserAuthService


class _StubAsyncClient:
    captured: dict = {}

    def __init__(self, timeout=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _StubAsyncClient.captured = {"url": url, "headers": headers, "json": json}
        response = MagicMock()
        response.status_code = 200
        response.json = MagicMock(
            return_value={"User": {"Id": "jf-1", "Name": "alice"}, "AccessToken": "tok"}
        )
        return response


@pytest.mark.asyncio
async def test_authenticate_by_name_sends_authorization_header(monkeypatch):
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _StubAsyncClient)
    _StubAsyncClient.captured = {}

    prefs = MagicMock()
    prefs.get_or_create_setting = MagicMock(return_value="device-1")
    jellyfin_repo = MagicMock()
    jellyfin_repo._base_url = "http://jellyfin:8096"

    service = JellyfinUserAuthService(
        auth_store=MagicMock(),
        jellyfin_repository=jellyfin_repo,
        preferences_service=prefs,
    )

    profile = await service._authenticate_with_jellyfin("alice", "pw")

    headers = _StubAsyncClient.captured["headers"]
    assert headers["Authorization"] == (
        'MediaBrowser Client="DroppedNeedle", Device="DroppedNeedle", '
        'DeviceId="device-1", Version="1.4.0"'
    )
    assert "X-Emby-Authorization" not in headers
    assert profile["jellyfin_user_id"] == "jf-1"
    assert profile["access_token"] == "tok"
