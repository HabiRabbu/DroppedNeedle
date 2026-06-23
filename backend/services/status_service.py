from typing import TYPE_CHECKING

from api.v1.schemas.common import ServiceStatus, StatusReport

if TYPE_CHECKING:
    from repositories.protocols.download_client import DownloadClientProtocol
    from services.native.library_manager import LibraryManager


class StatusService:
    """Aggregate health of the native engine's integrations: the download client
    (real ``health_check``) and the always-present library scanner."""

    def __init__(
        self,
        download_client: "DownloadClientProtocol",
        library_manager: "LibraryManager",
    ):
        self._client = download_client
        self._library = library_manager

    async def get_status(self) -> StatusReport:
        library_ok = self._library.is_configured()
        services = {
            "download_client": await self._client.health_check(),
            "library": ServiceStatus(
                status="ok" if library_ok else "error",
                message="Library scanner available" if library_ok else "Library not configured",
            ),
        }

        overall_status = "ok"
        if any(s.status == "error" for s in services.values()):
            overall_status = "error"
        elif any(s.status != "ok" for s in services.values()):
            overall_status = "degraded"

        return StatusReport(status=overall_status, services=services)
