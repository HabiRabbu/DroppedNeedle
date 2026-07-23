"""Dispatch claimed Library Management modes through the durable supervisor."""

from __future__ import annotations

import json
import time

from core.exceptions import ConflictError, StaleRevisionError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.library_management_planner import LibraryManagementPlanner
from services.native.library_management_publisher import LibraryManagementPublisher
from services.native.library_management_undo_service import LibraryManagementUndoService
from services.native.library_management_baseline_service import (
    LibraryManagementBaselineService,
)
from services.native.library_management_duplicate_service import (
    LibraryManagementDuplicateService,
)


class LibraryManagementWorker:
    def __init__(
        self,
        store: NativeLibraryStore,
        planner: LibraryManagementPlanner,
        publisher: LibraryManagementPublisher,
        undo: LibraryManagementUndoService,
        baseline: LibraryManagementBaselineService,
        duplicates: LibraryManagementDuplicateService,
    ) -> None:
        self._store = store
        self._planner = planner
        self._publisher = publisher
        self._undo = undo
        self._baseline = baseline
        self._duplicates = duplicates

    async def run_claimed(self, job: dict, worker_id: str) -> dict:
        job_id = str(job["id"])
        snapshot = await self._store.get_library_management_job_snapshot(job_id)
        if snapshot is None:
            return await self._store.finish_operation_job(
                job_id,
                worker_id,
                state="failed",
                terminal_code="MISSING_SNAPSHOT",
                now=time.time(),
            )
        if snapshot.mode == "undo" and snapshot.phase == "planning":
            try:
                await self._undo.run_claimed_preview(job, worker_id)
            except StaleRevisionError:
                return await self._store.finish_operation_job(
                    job_id,
                    worker_id,
                    state="failed",
                    terminal_code="STALE_INPUT",
                    now=time.time(),
                )
            except ValidationError:
                return await self._store.finish_operation_job(
                    job_id,
                    worker_id,
                    state="failed",
                    terminal_code="PLANNING_FAILED",
                    now=time.time(),
                )
            current = await self._store.get_operation_job(job_id)
            if current is None:
                raise ValidationError("Undo job disappeared after planning.")
            return current
        if snapshot.mode == "baseline_restore" and snapshot.phase == "planning":
            try:
                await self._baseline.run_claimed_preview(job, worker_id)
            except StaleRevisionError:
                return await self._store.finish_operation_job(
                    job_id,
                    worker_id,
                    state="failed",
                    terminal_code="STALE_INPUT",
                    now=time.time(),
                )
            except ValidationError:
                return await self._store.finish_operation_job(
                    job_id,
                    worker_id,
                    state="failed",
                    terminal_code="PLANNING_FAILED",
                    now=time.time(),
                )
            current = await self._store.get_operation_job(job_id)
            if current is None:
                raise ValidationError(
                    "Baseline restore job disappeared after planning."
                )
            return current
        if snapshot.mode == "duplicate_resolution" and snapshot.phase == "planning":
            try:
                await self._duplicates.run_claimed_preview(job, worker_id)
            except StaleRevisionError:
                return await self._store.finish_operation_job(
                    job_id,
                    worker_id,
                    state="failed",
                    terminal_code="STALE_INPUT",
                    now=time.time(),
                )
            except ValidationError:
                return await self._store.finish_operation_job(
                    job_id,
                    worker_id,
                    state="failed",
                    terminal_code="PLANNING_FAILED",
                    now=time.time(),
                )
            current = await self._store.get_operation_job(job_id)
            if current is None:
                raise ValidationError(
                    "Duplicate-resolution job disappeared after planning."
                )
            return current
        if snapshot.mode in {
            "apply",
            "automatic_apply",
            "undo",
            "baseline_restore",
            "duplicate_resolution",
        } and snapshot.phase in {
            "applying",
            "undoing",
            "restoring",
        }:
            return await self._run_apply(job_id, worker_id)
        if snapshot.mode != "preview":
            return await self._store.finish_operation_job(
                job_id,
                worker_id,
                state="failed",
                terminal_code="MODE_NOT_AVAILABLE",
                now=time.time(),
            )
        try:
            planned = await self._planner.run_claimed_preview(job, worker_id)
        except StaleRevisionError:
            return await self._store.finish_operation_job(
                job_id,
                worker_id,
                state="failed",
                terminal_code="STALE_INPUT",
                now=time.time(),
            )
        except ValidationError:
            return await self._store.finish_operation_job(
                job_id,
                worker_id,
                state="failed",
                terminal_code="PLANNING_FAILED",
                now=time.time(),
            )
        current = await self._store.get_operation_job(job_id)
        if current is None:
            raise ValidationError("Library management job disappeared after planning.")
        if planned.origin == "scan_discovered" and planned.phase == "ready":
            summary = json.loads(planned.summary_json)
            if (
                int(summary.get("blocked_count", 0)) == 0
                and int(summary.get("stale_count", 0)) == 0
            ):
                if planned.preview_token_hash is None:
                    return current
                try:
                    return await self._store.begin_library_management_apply(
                        job_id,
                        preview_token_hash=planned.preview_token_hash,
                        expected_job_revision=int(current["row_revision"]),
                        idempotency_key=f"automatic-scan-apply:{job_id}",
                        now=time.time(),
                    )
                except (StaleRevisionError, ValidationError):
                    return current
        return current

    async def _run_apply(self, job_id: str, worker_id: str) -> dict:
        snapshot = await self._store.get_library_management_job_snapshot(job_id)
        if snapshot is None:
            raise ValidationError("The management apply snapshot is missing.")
        while True:
            controlled = await self._store.checkpoint_operation_control(
                job_id, worker_id, now=time.time()
            )
            if controlled is not None and controlled["state"] != "running":
                return controlled
            work = await self._store.claim_operation_work(
                job_id, worker_id, now=time.time()
            )
            if work is None:
                return await self._store.finish_library_management_apply(
                    job_id, worker_id, now=time.time()
                )
            ordinal = int(work["ordinal"])
            try:
                items = (
                    await self._store.get_library_management_bundle_plan_items(
                        job_id, ordinal
                    )
                    if snapshot.mode == "duplicate_resolution"
                    else []
                )
                if (
                    snapshot.mode == "duplicate_resolution"
                    and items
                    and all(
                        json.loads(item.diff_json)
                        .get("duplicate_resolution", {})
                        .get("action")
                        == "keep_existing"
                        for item in items
                    )
                ):
                    await self._store.complete_operation_work(
                        job_id,
                        ordinal,
                        worker_id=worker_id,
                        expected_work_revision=int(work["row_revision"]),
                        state="succeeded",
                        result_json=json.dumps(
                            {"resolution": "kept_existing", "filesystem_writes": 0},
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        failure_code=None,
                        completed_at=time.time(),
                    )
                    continue
                await self._publisher.publish_bundle(job_id, ordinal, worker_id)
            except (StaleRevisionError, ConflictError) as error:
                current = await self._store.get_operation_work_item(job_id, ordinal)
                if current is not None and current["state"] == "succeeded":
                    continue
                await self._store.complete_operation_work(
                    job_id,
                    ordinal,
                    worker_id=worker_id,
                    expected_work_revision=int(work["row_revision"]),
                    state="skipped",
                    result_json=None,
                    failure_code=(
                        "STALE_DESTINATION"
                        if isinstance(error, ConflictError)
                        else "STALE_INPUT"
                    ),
                    completed_at=time.time(),
                )
            except (ValidationError, OSError):
                current = await self._store.get_operation_work_item(job_id, ordinal)
                if current is not None and current["state"] == "succeeded":
                    continue
                await self._store.complete_operation_work(
                    job_id,
                    ordinal,
                    worker_id=worker_id,
                    expected_work_revision=int(work["row_revision"]),
                    state="failed",
                    result_json=None,
                    failure_code="PUBLICATION_FAILED",
                    completed_at=time.time(),
                )
