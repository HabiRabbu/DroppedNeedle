import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import msgspec
import pytest

from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_management import LibraryManagementJobSnapshot
from services.native.library_management_planner import LibraryManagementPlanner
from services.native.library_management_publisher import LibraryManagementPublisher
from services.native.library_management_worker import LibraryManagementWorker
from services.native.library_management_undo_service import LibraryManagementUndoService
from services.native.library_management_baseline_service import (
    LibraryManagementBaselineService,
)
from services.native.library_management_duplicate_service import (
    LibraryManagementDuplicateService,
)


def _snapshot() -> LibraryManagementJobSnapshot:
    return LibraryManagementJobSnapshot(
        job_id="management-1",
        mode="apply",
        origin="manual",
        phase="applying",
        selection_json="{}",
        profile_revision="profile",
        settings_revision="settings",
        naming_revision="naming",
        policy_revision="policy",
        catalog_revision=1,
        profile_snapshot_json="{}",
    )


def _worker() -> tuple[LibraryManagementWorker, AsyncMock, AsyncMock]:
    store = AsyncMock(spec=NativeLibraryStore)
    publisher = AsyncMock(spec=LibraryManagementPublisher)
    worker = LibraryManagementWorker(
        store,
        AsyncMock(spec=LibraryManagementPlanner),
        publisher,
        AsyncMock(spec=LibraryManagementUndoService),
        AsyncMock(spec=LibraryManagementBaselineService),
        AsyncMock(spec=LibraryManagementDuplicateService),
    )
    store.get_library_management_job_snapshot.return_value = _snapshot()
    store.checkpoint_operation_control.return_value = None
    store.finish_library_management_apply.return_value = {
        "id": "management-1",
        "state": "succeeded",
    }
    return worker, store, publisher


@pytest.mark.asyncio
async def test_apply_worker_publishes_each_bundle_then_finishes() -> None:
    worker, store, publisher = _worker()
    store.claim_operation_work.side_effect = [
        {"ordinal": 0, "row_revision": 2, "state": "running"},
        None,
    ]

    result = await worker.run_claimed({"id": "management-1"}, "management-worker")

    assert result["state"] == "succeeded"
    publisher.publish_bundle.assert_awaited_once_with(
        "management-1", 0, "management-worker"
    )
    store.finish_library_management_apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_worker_honours_control_only_outside_critical_publish() -> None:
    worker, store, publisher = _worker()
    entered_publish = asyncio.Event()
    release_publish = asyncio.Event()

    async def publish(*_args) -> None:
        entered_publish.set()
        await release_publish.wait()

    publisher.publish_bundle.side_effect = publish
    store.claim_operation_work.side_effect = [
        {"ordinal": 0, "row_revision": 2, "state": "running"},
        None,
    ]
    store.checkpoint_operation_control.side_effect = [
        None,
        {
            "id": "management-1",
            "state": "paused",
            "control_request": "none",
        },
    ]

    task = asyncio.create_task(
        worker.run_claimed({"id": "management-1"}, "management-worker")
    )
    await entered_publish.wait()
    assert store.checkpoint_operation_control.await_count == 1
    release_publish.set()
    result = await task

    assert result["state"] == "paused"
    assert store.checkpoint_operation_control.await_count == 2
    store.finish_library_management_apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_baseline_restore_preview_dispatches_to_baseline_planner() -> None:
    worker, store, _publisher = _worker()
    snapshot = _snapshot()
    snapshot.mode = "baseline_restore"
    snapshot.phase = "planning"
    store.get_library_management_job_snapshot.return_value = snapshot
    store.get_operation_job.return_value = {
        "id": "management-1",
        "state": "ready",
    }

    result = await worker.run_claimed({"id": "management-1"}, "management-worker")

    assert result["state"] == "ready"
    worker._baseline.run_claimed_preview.assert_awaited_once_with(
        {"id": "management-1"}, "management-worker"
    )


@pytest.mark.asyncio
async def test_duplicate_preview_dispatches_to_duplicate_planner() -> None:
    worker, store, _publisher = _worker()
    snapshot = _snapshot()
    snapshot.mode = "duplicate_resolution"
    snapshot.phase = "planning"
    store.get_library_management_job_snapshot.return_value = snapshot
    store.get_operation_job.return_value = {
        "id": "management-1",
        "state": "ready",
    }

    result = await worker.run_claimed({"id": "management-1"}, "management-worker")

    assert result["state"] == "ready"
    worker._duplicates.run_claimed_preview.assert_awaited_once_with(
        {"id": "management-1"}, "management-worker"
    )


@pytest.mark.asyncio
async def test_scan_preview_begins_automatic_apply_without_browser_confirmation() -> (
    None
):
    worker, store, _publisher = _worker()
    snapshot = _snapshot()
    snapshot.mode = "preview"
    snapshot.origin = "scan_discovered"
    snapshot.phase = "planning"
    snapshot.preview_token_hash = "proof"
    ready = msgspec.structs.replace(
        snapshot,
        phase="ready",
        summary_json='{"blocked_count":0,"stale_count":0}',
    )
    store.get_library_management_job_snapshot.return_value = snapshot
    store.get_operation_job.return_value = {
        "id": "management-1",
        "state": "ready",
        "row_revision": 4,
    }
    store.begin_library_management_apply.return_value = {
        "id": "management-1",
        "state": "queued",
    }
    worker._planner.run_claimed_preview.return_value = ready

    result = await worker.run_claimed({"id": "management-1"}, "management-worker")

    assert result["state"] == "queued"
    store.begin_library_management_apply.assert_awaited_once()
    call = store.begin_library_management_apply.await_args
    assert call.args == ("management-1",)
    assert call.kwargs["preview_token_hash"] == "proof"
    assert call.kwargs["expected_job_revision"] == 4
    assert call.kwargs["idempotency_key"] == "automatic-scan-apply:management-1"
    assert call.kwargs["now"] > 0


@pytest.mark.asyncio
async def test_scan_preview_with_blockers_remains_held_and_inert() -> None:
    worker, store, _publisher = _worker()
    snapshot = _snapshot()
    snapshot.mode = "preview"
    snapshot.origin = "scan_discovered"
    snapshot.phase = "planning"
    snapshot.preview_token_hash = "proof"
    ready = msgspec.structs.replace(
        snapshot,
        phase="ready",
        summary_json='{"blocked_count":1,"stale_count":0}',
    )
    store.get_library_management_job_snapshot.return_value = snapshot
    store.get_operation_job.return_value = {
        "id": "management-1",
        "state": "ready",
        "row_revision": 4,
    }
    worker._planner.run_claimed_preview.return_value = ready

    result = await worker.run_claimed({"id": "management-1"}, "management-worker")

    assert result["state"] == "ready"
    store.begin_library_management_apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_keep_existing_duplicate_is_durable_without_filesystem_publish() -> None:
    worker, store, publisher = _worker()
    snapshot = _snapshot()
    snapshot.mode = "duplicate_resolution"
    store.get_library_management_job_snapshot.return_value = snapshot
    store.claim_operation_work.side_effect = [
        {"ordinal": 0, "row_revision": 2, "state": "running"},
        None,
    ]
    store.get_library_management_bundle_plan_items.return_value = [
        SimpleNamespace(
            diff_json=(
                '{"duplicate_resolution":{"action":"keep_existing"},'
                '"requires_write":false}'
            )
        )
    ]

    result = await worker.run_claimed({"id": "management-1"}, "management-worker")

    assert result["state"] == "succeeded"
    publisher.publish_bundle.assert_not_awaited()
    store.complete_operation_work.assert_awaited_once()
    values = store.complete_operation_work.await_args.kwargs
    assert values["state"] == "succeeded"
    assert values["result_json"] == (
        '{"filesystem_writes":0,"resolution":"kept_existing"}'
    )
