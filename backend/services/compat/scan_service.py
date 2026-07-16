"""Hosted Subsonic scan status and guarded native scan start."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from core.exceptions import ConfigurationError, ConflictError
from core.task_registry import TaskRegistry
from infrastructure.persistence.scan_state_store import ScanStateStore
from services.native.library_scanner import LibraryScanner
from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)


def _log_scan_error(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Hosted compatibility scan task failed",
            exc_info=(type(exception), exception, exception.__traceback__),
        )


class CompatScanService:
    def __init__(
        self,
        scan_state: ScanStateStore,
        scanner: LibraryScanner,
        preferences: PreferencesService,
    ) -> None:
        self._state = scan_state
        self._scanner = scanner
        self._preferences = preferences

    async def status(self) -> tuple[bool, int]:
        state = await self._state.get_state()
        return state["status"] == "scanning", int(state["processed_files"])

    async def start(self) -> None:
        state = await self._state.get_state()
        if state["status"] == "scanning":
            raise ConflictError("A library scan is already running")
        paths = [
            Path(path)
            for path in self._preferences.get_library_settings_raw().library_paths
        ]
        if not paths:
            raise ConfigurationError("No native library paths are configured")
        task = asyncio.create_task(self._scanner.scan(paths, force=False))
        try:
            TaskRegistry.get_instance().register("library-scan", task)
        except RuntimeError as exc:
            task.cancel()
            raise ConflictError("A library scan is already running") from exc
        task.add_done_callback(_log_scan_error)
