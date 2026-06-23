"""Tests for SettingsService.verify_navidrome / verify_youtube / verify_lastfm."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.settings_service import (
    SettingsService,
    NavidromeVerifyResult,
    YouTubeVerifyResult,
    LastFmVerifyResult,
)


def _make_service(*, preferences=None):
    prefs = preferences or MagicMock()
    cache = MagicMock()
    cache.clear_by_prefix = AsyncMock(return_value=0)
    service = SettingsService(
        preferences_service=prefs,
        cache=cache,
    )
    return service


@pytest.mark.asyncio
async def test_verify_navidrome_success():
    prefs = MagicMock()
    raw = MagicMock()
    raw.password = "real-password"
    prefs.get_navidrome_connection_raw = MagicMock(return_value=raw)

    service = _make_service(preferences=prefs)

    from api.v1.schemas.settings import NavidromeConnectionSettings
    settings = NavidromeConnectionSettings(
        enabled=True,
        navidrome_url="http://navidrome.local",
        username="admin",
        password="••••••••",
    )

    mock_repo_instance = MagicMock()
    mock_repo_instance.ping = AsyncMock(return_value=True)

    with patch("infrastructure.validators.validate_service_url"), \
         patch("services.settings_service.get_settings", return_value=MagicMock()), \
         patch("services.settings_service.get_http_client", return_value=MagicMock()), \
         patch("repositories.navidrome_repository.NavidromeRepository") as MockRepo:
        MockRepo.return_value = mock_repo_instance
        MockRepo.reset_circuit_breaker = MagicMock()

        result = await service.verify_navidrome(settings)

    assert isinstance(result, NavidromeVerifyResult)
    assert result.valid is True
    assert "success" in result.message.lower()


@pytest.mark.asyncio
async def test_verify_navidrome_ping_fail():
    prefs = MagicMock()
    raw = MagicMock()
    raw.password = "real-password"
    prefs.get_navidrome_connection_raw = MagicMock(return_value=raw)

    service = _make_service(preferences=prefs)

    from api.v1.schemas.settings import NavidromeConnectionSettings
    settings = NavidromeConnectionSettings(
        enabled=True,
        navidrome_url="http://navidrome.local",
        username="admin",
        password="real-password",
    )

    mock_repo_instance = MagicMock()
    mock_repo_instance.ping = AsyncMock(return_value=False)

    with patch("infrastructure.validators.validate_service_url"), \
         patch("services.settings_service.get_settings", return_value=MagicMock()), \
         patch("services.settings_service.get_http_client", return_value=MagicMock()), \
         patch("repositories.navidrome_repository.NavidromeRepository") as MockRepo:
        MockRepo.return_value = mock_repo_instance
        MockRepo.reset_circuit_breaker = MagicMock()

        result = await service.verify_navidrome(settings)

    assert result.valid is False


@pytest.mark.asyncio
async def test_verify_youtube_success():
    service = _make_service()

    from api.v1.schemas.settings import YouTubeConnectionSettings
    settings = YouTubeConnectionSettings(
        enabled=True,
        api_key="test-key",
        daily_quota_limit=100,
    )

    mock_repo_instance = MagicMock()
    mock_repo_instance.verify_api_key = AsyncMock(return_value=(True, "Valid"))

    with patch("services.settings_service.get_settings", return_value=MagicMock()), \
         patch("services.settings_service.get_http_client", return_value=MagicMock()), \
         patch("repositories.youtube.YouTubeRepository") as MockRepo:
        MockRepo.return_value = mock_repo_instance

        result = await service.verify_youtube(settings)

    assert isinstance(result, YouTubeVerifyResult)
    assert result.valid is True


@pytest.mark.asyncio
async def test_verify_lastfm_api_key_invalid():
    prefs = MagicMock()
    current = MagicMock()
    current.shared_secret = "real-secret"
    current.session_key = ""
    prefs.get_lastfm_connection = MagicMock(return_value=current)

    service = _make_service(preferences=prefs)

    from api.v1.schemas.settings import LastFmConnectionSettings
    settings = LastFmConnectionSettings(
        enabled=True,
        api_key="bad-key",
        shared_secret="real-secret",
        session_key="",
    )

    mock_repo_instance = MagicMock()
    mock_repo_instance.validate_api_key = AsyncMock(return_value=(False, "Invalid API key"))

    with patch("services.settings_service.get_settings", return_value=MagicMock()), \
         patch("services.settings_service.get_http_client", return_value=MagicMock()), \
         patch("repositories.lastfm_repository.LastFmRepository") as MockRepo:
        MockRepo.return_value = mock_repo_instance

        result = await service.verify_lastfm(settings)

    assert isinstance(result, LastFmVerifyResult)
    assert result.valid is False
    assert "invalid" in result.message.lower()


@pytest.mark.asyncio
async def test_verify_lastfm_with_session_key():
    prefs = MagicMock()
    current = MagicMock()
    current.shared_secret = "real-secret"
    current.session_key = "real-session-key"
    prefs.get_lastfm_connection = MagicMock(return_value=current)

    service = _make_service(preferences=prefs)

    from api.v1.schemas.settings import LastFmConnectionSettings, LASTFM_SECRET_MASK
    settings = LastFmConnectionSettings(
        enabled=True,
        api_key="good-key",
        shared_secret=LASTFM_SECRET_MASK,
        session_key=LASTFM_SECRET_MASK,
    )

    mock_repo_instance = MagicMock()
    mock_repo_instance.validate_api_key = AsyncMock(return_value=(True, "OK"))
    mock_repo_instance.validate_session = AsyncMock(return_value=(True, "Session valid"))

    with patch("services.settings_service.get_settings", return_value=MagicMock()), \
         patch("services.settings_service.get_http_client", return_value=MagicMock()), \
         patch("repositories.lastfm_repository.LastFmRepository") as MockRepo:
        MockRepo.return_value = mock_repo_instance

        result = await service.verify_lastfm(settings)

    assert result.valid is True
    assert "session" in result.message.lower()


@pytest.mark.asyncio
async def test_verify_download_client_uses_submitted_values():
    from models.common import ServiceStatus
    from api.v1.schemas.settings import DownloadClientConnectionSettings

    service = _make_service()
    settings = DownloadClientConnectionSettings(url="https://slskd.example.com", api_key="typed-key")

    repo = MagicMock()
    repo.health_check = AsyncMock(
        return_value=ServiceStatus(status="ok", version="0.25.1.0", message="slskd 0.25.1.0")
    )
    with patch("core.dependencies.build_slskd_repository", return_value=repo) as build:
        result = await service.verify_download_client(settings)

    assert result.status == "ok"
    assert result.version == "0.25.1.0"
    build.assert_called_once_with("https://slskd.example.com", "typed-key")


@pytest.mark.asyncio
async def test_verify_download_client_masked_key_falls_back_to_stored():
    from models.common import ServiceStatus
    from api.v1.schemas.settings import (
        DownloadClientConnectionSettings,
        DOWNLOAD_CLIENT_API_KEY_MASK,
    )

    prefs = MagicMock()
    prefs.get_download_client_settings_raw = MagicMock(
        return_value=MagicMock(api_key="real-stored-key")
    )
    service = _make_service(preferences=prefs)
    settings = DownloadClientConnectionSettings(
        url="https://slskd.example.com", api_key=DOWNLOAD_CLIENT_API_KEY_MASK
    )

    repo = MagicMock()
    repo.health_check = AsyncMock(
        return_value=ServiceStatus(status="ok", version="1", message="ok")
    )
    with patch("core.dependencies.build_slskd_repository", return_value=repo) as build:
        result = await service.verify_download_client(settings)

    assert result.status == "ok"
    build.assert_called_once_with("https://slskd.example.com", "real-stored-key")


@pytest.mark.asyncio
async def test_verify_download_client_invalid_url_returns_error():
    from api.v1.schemas.settings import DownloadClientConnectionSettings

    service = _make_service()
    # Empty url survives __post_init__ unchanged, so validate_service_url rejects it.
    settings = DownloadClientConnectionSettings(url="", api_key="k")

    result = await service.verify_download_client(settings)

    assert result.status == "error"
    assert "URL" in result.message
