from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import ExternalServiceError, JellyfinAuthError
from repositories.jellyfin_repository import JellyfinRepository


def _repository(response: MagicMock) -> tuple[JellyfinRepository, AsyncMock]:
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    repository = JellyfinRepository(
        client,
        AsyncMock(),
        base_url="http://jellyfin:8096",
        api_key="secret",
    )
    JellyfinRepository.reset_circuit_breaker()
    return repository, client


@pytest.mark.asyncio
async def test_refresh_library_uses_live_verified_global_endpoint() -> None:
    response = MagicMock(status_code=204)
    repository, client = _repository(response)

    await repository.refresh_library()

    client.request.assert_awaited_once_with(
        "POST",
        "http://jellyfin:8096/Library/Refresh",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": 'MediaBrowser Token="secret"',
        },
        timeout=15.0,
    )


@pytest.mark.asyncio
async def test_refresh_library_maps_auth_failure() -> None:
    repository, _client = _repository(MagicMock(status_code=401))

    with pytest.raises(JellyfinAuthError):
        await repository.refresh_library()


@pytest.mark.asyncio
async def test_refresh_library_retries_typed_server_failure() -> None:
    repository, client = _repository(MagicMock(status_code=503))

    with (
        patch("infrastructure.resilience.retry.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(ExternalServiceError),
    ):
        await repository.refresh_library()

    assert client.request.await_count == 3
