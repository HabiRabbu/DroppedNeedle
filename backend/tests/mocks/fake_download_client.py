"""``FakeDownloadClient`` - an in-memory second ``DownloadClientProtocol`` impl.

Its purpose is the conformance contract test (``test_download_client_protocol_contract``):
a second concrete implementation proves the "a hypothetical second client needs
zero changes to ``services/native``" claim, and that the boundary is not
slskd-shaped. It uses no httpx and no FastAPI.

Method signatures MUST stay byte-identical to ``DownloadClientProtocol`` (the
contract test compares ``inspect.signature``), so this module deliberately does
NOT use ``from __future__ import annotations``.
"""

from pathlib import Path

from models.common import ServiceStatus
from repositories.protocols.download_client import (
    DownloadFileRef,
    DownloadSearchResult,
    DownloadTaskStatus,
    MountDiagnosis,
    TaskRef,
)


class FakeDownloadClient:
    def __init__(self) -> None:
        self._enqueued: dict[str, list[str]] = {}

    @property
    def client_name(self) -> str:
        return "fake"

    def is_configured(self) -> bool:
        return True

    async def health_check(self) -> ServiceStatus:
        return ServiceStatus(status="ok", version="fake-1.0", message="fake")

    async def search_album(
        self,
        artist_name: str,
        album_title: str,
        year: int | None = None,
        track_count: int | None = None,
        *,
        timeout: float = 30.0,
    ) -> list[DownloadSearchResult]:
        return [
            DownloadSearchResult(
                username="fake-peer",
                filename=f"{artist_name}/{album_title}/01 track.flac",
                parent_directory=f"{artist_name} - {album_title}",
                size=10_000_000,
                extension="flac",
            )
        ]

    async def search_track(
        self,
        artist_name: str,
        track_title: str,
        album_title: str | None = None,
        duration_seconds: int | None = None,
        *,
        timeout: float = 30.0,
    ) -> list[DownloadSearchResult]:
        return [
            DownloadSearchResult(
                username="fake-peer",
                filename=f"{artist_name}/{track_title}.flac",
                parent_directory=f"{artist_name} - {album_title or ''}",
                size=10_000_000,
                extension="flac",
            )
        ]

    async def enqueue(self, files: list[DownloadFileRef]) -> TaskRef:
        username = files[0].username if files else "fake-peer"
        filenames = [f.filename for f in files]
        self._enqueued[username] = filenames
        return TaskRef(username=username, filenames=filenames)

    async def get_status(self, task_ref: TaskRef) -> DownloadTaskStatus:
        total = len(task_ref.filenames)
        return DownloadTaskStatus(
            task_id="",
            status="completed",
            files_total=total,
            files_completed=total,
            progress_percent=100.0,
        )

    async def cancel(self, task_ref: TaskRef) -> bool:
        self._enqueued.pop(task_ref.username, None)
        return True

    async def get_file_path(self, username: str, remote_filename: str, size: int | None = None) -> Path | None:
        return Path("/fake/downloads") / remote_filename.replace("\\", "/").lstrip("/")

    async def diagnose_downloads_mount(self) -> MountDiagnosis:
        return MountDiagnosis(supported=False)
