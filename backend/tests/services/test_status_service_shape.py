from unittest.mock import AsyncMock, MagicMock

import pytest

from models.common import ServiceStatus
from services.status_service import StatusService


def _make_service(*, client_status="ok", library_configured=True):
    client = MagicMock()
    client.health_check = AsyncMock(
        return_value=ServiceStatus(status=client_status, message="slskd")
    )
    library = MagicMock()
    library.is_configured = MagicMock(return_value=library_configured)
    return StatusService(client, library)


@pytest.mark.asyncio
async def test_status_report_has_download_client_and_library_keys_not_lidarr():
    report = await _make_service().get_status()
    assert "download_client" in report.services
    assert "library" in report.services
    assert "lidarr" not in report.services
    assert report.status == "ok"


@pytest.mark.asyncio
async def test_status_report_error_when_download_client_unhealthy():
    report = await _make_service(client_status="error").get_status()
    assert report.status == "error"


@pytest.mark.asyncio
async def test_status_report_error_when_library_not_configured():
    report = await _make_service(library_configured=False).get_status()
    assert report.services["library"].status == "error"
    assert report.status == "error"
