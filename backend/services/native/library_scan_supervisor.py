"""Stable target supervisor that resolves settings-dependent services each tick."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from core.task_registry import TaskRegistry
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_scan_coordinator import LibraryScanCoordinator
from services.native.library_scan_scheduler import LibraryAutomaticScanScheduler

logger = logging.getLogger(__name__)
SUPERVISOR_INTERVAL_SECONDS = 1.0
SUPERVISOR_TASK_NAME = "target-library-scan-supervisor"


def _log_supervisor_error(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "Target scan supervisor stopped unexpectedly",
            exc_info=(type(error), error, error.__traceback__),
        )


def start_target_scan_supervisor(
    coordinator_getter: Callable[[], LibraryScanCoordinator],
    root_paths_getter: Callable[[], dict[str, Path]],
    *,
    scheduler_getter: Callable[[], LibraryAutomaticScanScheduler] | None = None,
    resolver_getter: Callable[[], LibraryPolicyResolver] | None = None,
    schedule_settings_getter: Callable[[], dict[str, str]] | None = None,
) -> asyncio.Task[None]:
    registry = TaskRegistry.get_instance()
    if registry.is_running(SUPERVISOR_TASK_NAME):
        raise RuntimeError(f"Task '{SUPERVISOR_TASK_NAME}' is already running")
    task = asyncio.create_task(
        supervise_target_scans(
            coordinator_getter,
            root_paths_getter,
            scheduler_getter,
            resolver_getter,
            schedule_settings_getter,
        )
    )
    registry.register(SUPERVISOR_TASK_NAME, task)
    task.add_done_callback(_log_supervisor_error)
    return task


async def supervise_target_scans(
    coordinator_getter: Callable[[], LibraryScanCoordinator],
    root_paths_getter: Callable[[], dict[str, Path]],
    scheduler_getter: Callable[[], LibraryAutomaticScanScheduler] | None = None,
    resolver_getter: Callable[[], LibraryPolicyResolver] | None = None,
    schedule_settings_getter: Callable[[], dict[str, str]] | None = None,
    now_getter: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> None:
    try:
        await coordinator_getter().recover()
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001 - startup recovery failure must not kill the supervisor
        logger.exception("Target scan startup recovery failed")
    while True:
        try:
            coordinator = coordinator_getter()
            if (
                scheduler_getter is not None
                and resolver_getter is not None
                and schedule_settings_getter is not None
            ):
                schedule = schedule_settings_getter()
                await scheduler_getter().tick(
                    coordinator,
                    resolver_getter(),
                    frequency=schedule["frequency"],
                    daily_time=schedule["daily_time"],
                    timezone_name=schedule["timezone_name"],
                    now=now_getter(),
                )
            await coordinator.run_once(root_paths_getter())
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - the lifetime supervisor records and survives run failures
            logger.exception("Target scan supervisor iteration failed")
        try:
            await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break
