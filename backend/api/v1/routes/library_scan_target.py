"""Staged target scan APIs; mounted only after the authorized offline cutover."""

from __future__ import annotations

import time
from pathlib import PurePosixPath

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from api.v1.schemas.library_scan_target import (
    IdentificationControlRequestBody,
    IdentificationControlResponse,
    LegacyScanShimResponse,
    LibraryActivityItem,
    LibraryActivityResponse,
    ScanControlRequestBody,
    ScanControlResponse,
    ScanEstimateResponse,
    ScanRunCurrentResponse,
    ScanRunDetailResponse,
    ScanRunHistoryResponse,
    ScanRunRequestBody,
    ScanRunRequestedResponse,
)
from api.v1.schemas.library import LibraryScanStatusResponse
from core.dependencies import (
    LibraryPolicyResolverDep,
    TargetIdentificationQueueDep,
    TargetLibraryScanCoordinatorDep,
)
from core.exceptions import ValidationError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentAdminDep, CurrentUserDep
from models.library_work import ScanRequest, ScanScope
from services.native.library_activity_events import activity_events

router = APIRouter(
    route_class=MsgSpecRoute, prefix="/library", tags=["library-scan-target"]
)

_IDENTIFICATION_PRIORITY_LABELS = {
    20: "New and changed albums",
    30: "Administrator retries",
    40: "Existing-library backlog",
    50: "Supporting maintenance",
}


def _selected_scopes(
    body: ScanRunRequestBody, resolver: LibraryPolicyResolverDep
) -> list[ScanScope]:
    if body.expected_policy_revision != resolver.policy_revision:
        raise ValidationError(
            "The library policy changed. Refresh this page and try again."
        )
    selected = set(body.scope_ids)
    candidates: list[ScanScope] = []
    matched: set[str] = set()
    for root in resolver.settings.library_roots:
        selected_rules = [rule for rule in root.rules if rule.id in selected]
        matched.update(rule.id for rule in selected_rules)
        if root.id in selected:
            matched.add(root.id)
        if not selected or root.id in selected:
            candidates.append(
                ScanScope(
                    root_id=root.id,
                    scope_id=root.id,
                    relative_path=".",
                    effective_policy=root.policy,
                    policy_revision=resolver.policy_revision,
                )
            )
            continue
        for rule in root.rules:
            if rule.id in selected:
                candidates.append(
                    ScanScope(
                        root_id=root.id,
                        scope_id=rule.id,
                        relative_path=rule.relative_path,
                        effective_policy=rule.policy,
                        policy_revision=resolver.policy_revision,
                    )
                )
    if selected and matched != selected:
        raise ValidationError("One or more selected library scopes no longer exist.")
    scopes: list[ScanScope] = []
    for candidate in sorted(
        candidates,
        key=lambda scope: (
            scope.root_id,
            len(PurePosixPath(scope.relative_path).parts),
            scope.relative_path,
        ),
    ):
        candidate_path = PurePosixPath(candidate.relative_path)
        if any(
            existing.root_id == candidate.root_id
            and (
                existing.relative_path == "."
                or candidate_path.is_relative_to(PurePosixPath(existing.relative_path))
            )
            for existing in scopes
        ):
            continue
        scopes.append(candidate)
    return scopes


@router.get("/activity", response_model=LibraryActivityResponse)
async def library_activity(
    _: CurrentUserDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    identification: TargetIdentificationQueueDep,
) -> LibraryActivityResponse:
    runs = await coordinator.current()
    recent_history = await coordinator.history(limit=1)
    latest_failure = next(
        (
            run
            for run in recent_history
            if run.state == "failed"
            and run.terminal_at is not None
            and time.time() - run.terminal_at < 24 * 60 * 60
        ),
        None,
    )
    items: list[LibraryActivityItem] = []
    for run in runs[:1]:
        snapshot = await coordinator.snapshot(run.id)
        discovering = run.state == "discovering"
        total = (
            None
            if discovering
            else snapshot.counters.get("total_count")
            or snapshot.counters.get("discovered_count")
        )
        processed = snapshot.counters.get(
            "discovered_count" if discovering else "inspected_count", 0
        )
        items.append(
            LibraryActivityItem(
                kind="scan",
                state=run.state,
                label="Updating the local library",
                processed=processed,
                total=total,
                indeterminate=discovering or not bool(total),
                updated_at=run.updated_at,
                started_at=run.started_at,
                failure_event_id=latest_failure.id if latest_failure else None,
                failure_at=latest_failure.terminal_at if latest_failure else None,
            )
        )
    if not runs and latest_failure is not None:
        snapshot = await coordinator.snapshot(latest_failure.id)
        total = snapshot.counters.get("total_count") or snapshot.counters.get(
            "discovered_count"
        )
        items.append(
            LibraryActivityItem(
                kind="scan",
                state="failed",
                label="Updating the local library",
                processed=snapshot.counters.get("inspected_count", 0),
                total=total,
                indeterminate=not bool(total),
                updated_at=latest_failure.updated_at,
                started_at=latest_failure.started_at,
                failure_event_id=latest_failure.id,
                failure_at=latest_failure.terminal_at,
            )
        )
    identification_snapshot = await identification.activity_snapshot()
    counts = identification_snapshot["counts"]
    waiting = sum(counts.get(state, 0) for state in ("queued", "running", "paused"))
    foreground_operations = identification_snapshot["foreground_operation_count"]
    completed = sum(
        counts.get(state, 0) for state in ("succeeded", "needs_review", "failed")
    )
    if (
        waiting
        or foreground_operations
        or identification_snapshot["failure_event_id"] is not None
    ):
        control_state = identification_snapshot["control_state"]
        if control_state == "paused" and counts.get("running", 0):
            state = "pausing"
        elif control_state == "paused":
            state = "paused"
        elif waiting:
            state = "running"
        elif identification_snapshot["failure_event_id"] is not None:
            state = "failed"
        else:
            state = "idle"
        total = completed + waiting
        active_priority = identification_snapshot.get("active_priority")
        items.append(
            LibraryActivityItem(
                kind="identification",
                state=state,
                label="Identifying albums",
                processed=completed,
                total=total or None,
                indeterminate=not bool(total),
                updated_at=float(
                    identification_snapshot["updated_at"]
                    or identification_snapshot["failure_at"]
                    or 0.0
                ),
                started_at=identification_snapshot["started_at"],
                waiting_count=waiting,
                identified_count=counts.get("succeeded", 0),
                kept_local_count=identification_snapshot.get("kept_local_count", 0),
                needs_review_count=counts.get("needs_review", 0),
                failed_count=counts.get("failed", 0),
                deferred_count=identification_snapshot["deferred_count"],
                priority_band=(
                    _IDENTIFICATION_PRIORITY_LABELS.get(active_priority, "Queued work")
                    if active_priority is not None
                    else None
                ),
                oldest_backlog_at=identification_snapshot["started_at"],
                provider_unavailable=bool(identification_snapshot["deferred_count"]),
                control_revision=identification_snapshot["control_revision"],
                failure_event_id=identification_snapshot["failure_event_id"],
                failure_at=identification_snapshot["failure_at"],
                foreground_operation_count=foreground_operations,
            )
        )
    return LibraryActivityResponse(items=items)


@router.get("/activity/stream")
async def library_activity_stream(
    _: CurrentUserDep,
    identification: TargetIdentificationQueueDep,
):
    return StreamingResponse(
        activity_events(identification),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _identification_control_response(
    identification: TargetIdentificationQueueDep,
    revision: int,
) -> IdentificationControlResponse:
    snapshot = await identification.activity_snapshot()
    counts = snapshot["counts"]
    state = str(snapshot["control_state"])
    if state == "paused" and counts.get("running", 0):
        state = "pausing"
    return IdentificationControlResponse(state=state, row_revision=revision)


@router.post("/identification/pause", response_model=IdentificationControlResponse)
async def pause_identification(
    admin: CurrentAdminDep,
    identification: TargetIdentificationQueueDep,
    body: IdentificationControlRequestBody = MsgSpecBody(
        IdentificationControlRequestBody
    ),
) -> IdentificationControlResponse:
    revision = await identification.pause(
        admin.id, expected_revision=body.expected_revision
    )
    return await _identification_control_response(identification, revision)


@router.post("/identification/resume", response_model=IdentificationControlResponse)
async def resume_identification(
    _: CurrentAdminDep,
    identification: TargetIdentificationQueueDep,
    body: IdentificationControlRequestBody = MsgSpecBody(
        IdentificationControlRequestBody
    ),
) -> IdentificationControlResponse:
    revision = await identification.resume(expected_revision=body.expected_revision)
    return await _identification_control_response(identification, revision)


@router.get("/operations/stream")
async def library_operations_stream(
    _: CurrentAdminDep,
    identification: TargetIdentificationQueueDep,
):
    return await library_activity_stream(_, identification)


@router.post("/scan-runs", response_model=ScanRunRequestedResponse, status_code=202)
async def request_scan_run(
    current_admin: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    resolver: LibraryPolicyResolverDep,
    body: ScanRunRequestBody = MsgSpecBody(ScanRunRequestBody),
) -> ScanRunRequestedResponse:
    result = await coordinator.request_run(
        ScanRequest(
            kind=body.kind,
            trigger="manual",
            scopes=_selected_scopes(body, resolver),
            requested_by_user_id=current_admin.id,
            policy_revision=resolver.policy_revision,
        )
    )
    return ScanRunRequestedResponse(
        run_id=result.run_id,
        disposition=result.disposition,
        state=result.state,
        row_revision=result.row_revision,
        queued_reason=result.queued_reason,
        conflicting_kind=result.conflicting_kind,
    )


@router.get("/scan-runs/current", response_model=ScanRunCurrentResponse)
async def current_scan_runs(
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
) -> ScanRunCurrentResponse:
    runs = await coordinator.current()
    return ScanRunCurrentResponse(
        active=next((run for run in runs if run.state != "queued"), None),
        queued=next((run for run in runs if run.state == "queued"), None),
    )


@router.get("/scan-runs", response_model=ScanRunHistoryResponse)
async def scan_run_history(
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    limit: int = Query(default=50, ge=1, le=50),
    cursor: str | None = Query(default=None),
) -> ScanRunHistoryResponse:
    items, next_cursor = await coordinator.history_page(limit=limit, cursor=cursor)
    return ScanRunHistoryResponse(items=items, next_cursor=next_cursor)


@router.get("/scan-runs/estimate", response_model=ScanEstimateResponse)
async def estimate_scan_run(
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    resolver: LibraryPolicyResolverDep,
    scope_ids: list[str] = Query(default=[]),
) -> ScanEstimateResponse:
    scopes = _selected_scopes(
        ScanRunRequestBody(
            scope_ids=scope_ids,
            expected_policy_revision=resolver.policy_revision,
        ),
        resolver,
    )
    count, estimated_at = await coordinator.estimate(scopes)
    return ScanEstimateResponse(
        approximate=True,
        estimated_file_count=count,
        estimated_at=estimated_at,
    )


@router.get("/scan-runs/{run_id}", response_model=ScanRunDetailResponse)
async def scan_run_detail(
    run_id: str,
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
) -> ScanRunDetailResponse:
    return ScanRunDetailResponse(snapshot=await coordinator.snapshot(run_id))


async def _control(
    run_id: str,
    action: str,
    body: ScanControlRequestBody,
    coordinator: TargetLibraryScanCoordinatorDep,
) -> ScanControlResponse:
    result = await coordinator.control(run_id, action, body.expected_revision)
    return ScanControlResponse(
        run_id=result.run_id,
        state=result.state,
        row_revision=result.row_revision,
        event_revision=result.event_revision,
        stream_revision=result.stream_revision,
    )


@router.post("/scan-runs/{run_id}/pause", response_model=ScanControlResponse)
async def pause_scan_run(
    run_id: str,
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    body: ScanControlRequestBody = MsgSpecBody(ScanControlRequestBody),
) -> ScanControlResponse:
    return await _control(run_id, "pause", body, coordinator)


@router.post("/scan-runs/{run_id}/resume", response_model=ScanControlResponse)
async def resume_scan_run(
    run_id: str,
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    body: ScanControlRequestBody = MsgSpecBody(ScanControlRequestBody),
) -> ScanControlResponse:
    return await _control(run_id, "resume", body, coordinator)


@router.post("/scan-runs/{run_id}/stop", response_model=ScanControlResponse)
async def stop_scan_run(
    run_id: str,
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    body: ScanControlRequestBody = MsgSpecBody(ScanControlRequestBody),
) -> ScanControlResponse:
    return await _control(run_id, "stop", body, coordinator)


@router.post("/scan/start", response_model=LegacyScanShimResponse, status_code=202)
async def legacy_start_scan_shim(
    current_admin: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
    resolver: LibraryPolicyResolverDep,
    force: bool = Query(default=False),
) -> LegacyScanShimResponse:
    if force:
        raise ValidationError(
            "Force rescan has been replaced. Use Rescan files or Retry identification."
        )
    result = await coordinator.request_run(
        ScanRequest(
            kind="incremental",
            trigger="manual",
            requested_by_user_id=current_admin.id,
            policy_revision=resolver.policy_revision,
            scopes=_selected_scopes(
                ScanRunRequestBody(expected_policy_revision=resolver.policy_revision),
                resolver,
            ),
        )
    )
    return LegacyScanShimResponse(
        status=result.disposition,
        message="Library update requested.",
        run_id=result.run_id,
    )


@router.post("/scan/cancel", response_model=LegacyScanShimResponse)
async def legacy_cancel_scan_shim(
    _: CurrentAdminDep,
    coordinator: TargetLibraryScanCoordinatorDep,
) -> LegacyScanShimResponse:
    runs = await coordinator.current()
    active = next((run for run in runs if run.state != "queued"), None)
    if active is None:
        raise ValidationError("No library update is running.")
    await coordinator.control(active.id, "stop", active.row_revision)
    return LegacyScanShimResponse(
        status="stopping",
        message="Stopping the library update.",
        run_id=active.id,
    )


@router.get("/scan/status", response_model=LibraryScanStatusResponse)
async def legacy_scan_status_shim(
    _: CurrentUserDep,
    coordinator: TargetLibraryScanCoordinatorDep,
) -> LibraryScanStatusResponse:
    runs = await coordinator.current()
    if not runs:
        return LibraryScanStatusResponse()
    run = runs[0]
    snapshot = await coordinator.snapshot(run.id)
    counters = snapshot.counters
    total = counters.get("total_count") or counters.get("discovered_count", 0)
    return LibraryScanStatusResponse(
        status="scanning",
        total_files=total,
        processed_files=counters.get("inspected_count", 0),
        matched_files=counters.get("indexed_count", 0)
        + counters.get("unchanged_count", 0),
        failed_files=counters.get("errored_count", 0),
        started_at=run.started_at,
        updated_at=run.updated_at,
    )
