"""HTTP contracts for the staged target scan control plane."""

from __future__ import annotations

from typing import Literal

import msgspec

from infrastructure.msgspec_fastapi import AppStruct
from models.library_work import ScanRun, ScanRunSnapshot


class ScanRunRequestBody(AppStruct):
    kind: Literal["incremental", "rescan_files", "policy_reconcile"] = "incremental"
    scope_ids: list[str] = msgspec.field(default_factory=list)
    expected_policy_revision: str = ""


class ScanRunRequestedResponse(AppStruct):
    run_id: str
    disposition: Literal["started", "queued", "coalesced", "expanded", "conflict"]
    state: str
    row_revision: int
    queued_reason: str | None = None
    conflicting_kind: str | None = None
    estimated_file_count: int | None = None


class ScanControlRequestBody(AppStruct):
    expected_revision: int


class ScanControlResponse(AppStruct):
    run_id: str
    state: str
    row_revision: int
    event_revision: int
    stream_revision: int


class ScanRunCurrentResponse(AppStruct):
    active: ScanRun | None = None
    queued: ScanRun | None = None


class ScanRunHistoryResponse(AppStruct):
    items: list[ScanRun]
    next_cursor: str | None = None


class ScanRunDetailResponse(AppStruct):
    snapshot: ScanRunSnapshot


class LibraryActivityItem(AppStruct):
    kind: Literal["scan", "identification"]
    state: str
    label: str
    processed: int
    total: int | None = None
    indeterminate: bool = False
    updated_at: float = 0.0
    started_at: float | None = None
    waiting_count: int = 0
    identified_count: int = 0
    kept_local_count: int = 0
    needs_review_count: int = 0
    failed_count: int = 0
    deferred_count: int = 0
    priority_band: str | None = None
    oldest_backlog_at: float | None = None
    provider_unavailable: bool = False
    control_revision: int | None = None
    failure_event_id: str | None = None
    failure_at: float | None = None
    foreground_operation_count: int = 0


class LibraryActivityResponse(AppStruct):
    items: list[LibraryActivityItem]


class IdentificationControlRequestBody(AppStruct):
    expected_revision: int


class IdentificationControlResponse(AppStruct):
    state: Literal["running", "pausing", "paused"]
    row_revision: int


class ScanEstimateResponse(AppStruct):
    approximate: bool = True
    estimated_file_count: int | None = None
    estimated_at: float | None = None


class LegacyScanShimResponse(AppStruct):
    status: str
    message: str
    run_id: str | None = None
