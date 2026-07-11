"""Jellyfin 10.11+ only accepts API keys via ``Authorization: MediaBrowser
Token="<key>"`` - the legacy ``X-Emby-Token`` header 401s (issue #151). Every
outbound auth surface of the repository must send the modern header."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from repositories.jellyfin_repository import JellyfinRepository

EXPECTED_AUTH = 'MediaBrowser Token="test-api-key"'


def _make_repo(http_client: AsyncMock | None = None) -> JellyfinRepository:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return JellyfinRepository(
        http_client=http_client or AsyncMock(),
        cache=cache,
        base_url="http://jellyfin:8096",
        api_key="test-api-key",
        user_id="user-123",
    )


def _json_response(payload: bytes = b"{}") -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.content = payload
    response.headers = {"content-type": "application/json"}
    return response


@pytest.fixture(autouse=True)
def _reset_breaker():
    JellyfinRepository.reset_circuit_breaker()
    yield
    JellyfinRepository.reset_circuit_breaker()


@pytest.mark.asyncio
async def test_request_sends_authorization_header_not_emby_token():
    http_client = AsyncMock()
    http_client.request = AsyncMock(return_value=_json_response())
    repo = _make_repo(http_client)

    await repo._request("GET", "/System/Info")

    headers = http_client.request.await_args.kwargs["headers"]
    assert headers["Authorization"] == EXPECTED_AUTH
    assert "X-Emby-Token" not in headers


def test_get_auth_headers_uses_authorization_header():
    repo = _make_repo()

    headers = repo.get_auth_headers()

    assert headers == {"Authorization": EXPECTED_AUTH}


def test_stream_headers_use_authorization_header():
    repo = _make_repo()

    headers = repo._get_stream_headers()

    assert headers == {"Authorization": EXPECTED_AUTH}


@pytest.mark.asyncio
async def test_proxy_image_sends_authorization_header():
    http_client = AsyncMock()
    http_client.get = AsyncMock(return_value=_json_response(b"\x89PNG"))
    repo = _make_repo(http_client)

    await repo.proxy_image("item-1")

    headers = http_client.get.await_args.kwargs["headers"]
    assert headers["Authorization"] == EXPECTED_AUTH
    assert "X-Emby-Token" not in headers
