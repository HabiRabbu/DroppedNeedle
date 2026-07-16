"""Snapshot-based existing-identity audit and explicit safe-detach Apply."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from api.v1.schemas.library_operations import (
    OperationResponse,
    RepairCreateRequest,
    RepairEstimateResponse,
    RepairFindingListResponse,
    RepairFindingResponse,
)
from core.exceptions import ExternalServiceError, ResourceNotFoundError, ValidationError
from infrastructure.queue.priority_queue import RequestPriority
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.identification import IdentificationAttempt, IdentificationEvidenceRecord
from models.library_work import OperationJob, RepairFinding
from repositories.protocols.identification import IdentificationProviderProtocol
from services.native.album_evidence_engine import MATCHER_VERSION, AlbumEvidenceEngine
from services.native.album_identification_service import (
    _candidate_key,
    _to_grouping_track,
)
from services.native.conditional_fingerprint_service import FINGERPRINTER_VERSION
from services.native.identification_revisions import album_input_revisions
from services.native.library_operation_service import LibraryOperationService


class IdentityRepairService:
    def __init__(
        self,
        store: NativeLibraryStore,
        provider: IdentificationProviderProtocol | None = None,
        evidence: AlbumEvidenceEngine | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._evidence = evidence or AlbumEvidenceEngine()
        self._operations = LibraryOperationService(store)

    async def create(
        self,
        request: RepairCreateRequest,
        actor_user_id: str,
        *,
        now: float | None = None,
    ) -> OperationResponse:
        timestamp = time.time() if now is None else now
        job = OperationJob(
            id=str(uuid.uuid4()),
            kind="repair",
            requested_by_user_id=actor_user_id,
            input_catalog_revision=await self._store.get_catalog_revision(),
            idempotency_key=request.idempotency_key,
            created_at=timestamp,
        )
        row = await self._store.create_repair_operation(
            job,
            scope={
                "root_ids": request.root_ids,
                "legacy_only": request.source_matcher_version is None,
            },
            source_matcher_version=request.source_matcher_version,
            target_matcher_version=request.target_matcher_version,
        )
        return self._operations._response(row)

    async def estimate(self, root_ids: list[str]) -> RepairEstimateResponse:
        unique_root_ids = list(dict.fromkeys(root_ids))
        result = await self._store.estimate_repair_operation(unique_root_ids)
        return RepairEstimateResponse(
            identity_count=result["identity_count"],
            selected_root_count=len(unique_root_ids),
            queued_repair_count=result["queued_repair_count"],
        )

    async def run_claimed_audit(
        self,
        job: dict,
        worker_id: str,
        *,
        now: float | None = None,
        checkpoint: Callable[[], Awaitable[None]] | None = None,
    ) -> OperationResponse:
        timestamp = time.time() if now is None else now
        while True:
            controlled = await self._store.checkpoint_operation_control(
                str(job["id"]), worker_id, now=timestamp
            )
            if controlled is not None and controlled["state"] != "running":
                return self._operations._response(controlled)
            work = await self._store.claim_operation_work(
                str(job["id"]), worker_id, now=timestamp
            )
            if work is None:
                await self._store.mark_repair_ready(
                    str(job["id"]), worker_id, now=timestamp
                )
                return await self._operations.get(str(job["id"]))
            context = await self._store.get_album_identification_context(
                str(work["local_album_id"])
            )
            finding, attempt, evidence = await self._classify(
                str(job["id"]), work, context
            )
            await self._store.save_repair_finding_for_work(
                str(job["id"]),
                int(work["ordinal"]),
                worker_id=worker_id,
                expected_work_revision=int(work["row_revision"]),
                finding=finding,
                attempt=attempt,
                evidence=evidence,
                now=timestamp,
            )
            if checkpoint is not None:
                await checkpoint()

    async def begin_apply(
        self,
        job_id: str,
        *,
        expected_row_revision: int,
        confirmation: bool,
        now: float | None = None,
    ) -> OperationResponse:
        if not confirmation:
            raise ValidationError(
                "Confirm the repair report before applying safe detachments."
            )
        row = await self._store.start_repair_apply(
            job_id,
            expected_row_revision=expected_row_revision,
            now=time.time() if now is None else now,
        )
        return self._operations._response(row)

    async def run_claimed_apply(
        self,
        job: dict,
        worker_id: str,
        actor_user_id: str,
        *,
        now: float | None = None,
        checkpoint: Callable[[], Awaitable[None]] | None = None,
    ) -> OperationResponse:
        timestamp = time.time() if now is None else now
        while True:
            controlled = await self._store.checkpoint_operation_control(
                str(job["id"]), worker_id, now=timestamp
            )
            if controlled is not None and controlled["state"] != "running":
                return self._operations._response(controlled)
            work = await self._store.claim_operation_work(
                str(job["id"]), worker_id, now=timestamp
            )
            if work is None:
                done = await self._store.finish_operation_job(
                    str(job["id"]),
                    worker_id,
                    state="succeeded",
                    terminal_code="APPLY_COMPLETED",
                    now=timestamp,
                )
                return self._operations._response(done)
            await self._store.apply_repair_work(
                str(job["id"]),
                int(work["ordinal"]),
                worker_id=worker_id,
                expected_work_revision=int(work["row_revision"]),
                actor_user_id=actor_user_id,
                now=timestamp,
            )
            if checkpoint is not None:
                await checkpoint()

    async def findings(
        self,
        job_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
        finding_category: str | None = None,
    ) -> RepairFindingListResponse:
        if limit < 1 or limit > 200:
            raise ValidationError("Repair finding page size must be between 1 and 200.")
        categories = {
            "valid": ["valid"],
            "safe_detach": ["safe_detach"],
            "needs_review": ["needs_review"],
            "unverifiable": ["unverifiable", "stale"],
            "manual_identity": ["manual_identity"],
        }
        if finding_category is not None and finding_category not in categories:
            raise ValidationError("The repair finding category is invalid.")
        if await self._store.get_operation_job(job_id) is None:
            raise ResourceNotFoundError("Repair job not found.")
        cursor_updated_at: float | None = None
        cursor_id: str | None = None
        if cursor is not None:
            try:
                updated, cursor_id = cursor.split(":", 1)
                cursor_updated_at = float(updated)
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    "The repair finding cursor is invalid."
                ) from error
        result = await self._store.list_repair_findings(
            job_id,
            limit=limit,
            finding_codes=categories.get(finding_category),
            cursor_updated_at=cursor_updated_at,
            cursor_id=cursor_id,
        )
        rows = result["rows"]
        next_cursor = None
        if result["has_more"] and rows:
            next_cursor = f"{rows[-1]['updated_at']}:{rows[-1]['id']}"
        return RepairFindingListResponse(
            items=[
                RepairFindingResponse(
                    id=str(row["id"]),
                    local_album_id=str(row["local_album_id"]),
                    evidence_id=row["evidence_id"],
                    review_id=row["review_id"],
                    finding_code=str(row["finding_code"]),
                    reason_code=str(row["reason_code"]),
                    confidence=str(row["confidence"]),
                    apply_eligible=bool(row["apply_eligible"]),
                    state=str(row["state"]),
                    apply_result=row["apply_result"],
                    updated_at=float(row["updated_at"]),
                    row_revision=int(row["row_revision"]),
                )
                for row in rows
            ],
            next_cursor=next_cursor,
            has_more=bool(result["has_more"]),
        )

    async def _classify(
        self, job_id: str, work: dict, context: dict | None
    ) -> tuple[
        RepairFinding,
        IdentificationAttempt | None,
        list[IdentificationEvidenceRecord],
    ]:
        album_id = str(work["local_album_id"])
        if context is None or context["identity"] is None:
            return (
                self._finding(job_id, work, "stale", "IDENTITY_CHANGED", False),
                None,
                [],
            )
        identity = context["identity"]
        if identity["decision_source"] == "manual":
            return (
                self._finding(
                    job_id,
                    work,
                    "manual_identity",
                    "MANUAL_IDENTITY_REPORT_ONLY",
                    False,
                    identity_revision=int(identity["row_revision"]),
                ),
                None,
                [],
            )
        stored = await self._store.get_selected_album_evidence(album_id)
        if stored is None:
            stored = await self._store.get_latest_album_candidate_evidence(
                album_id,
                f"{identity['release_group_mbid']}:{identity['release_mbid'] or ''}",
            )
        attempt: IdentificationAttempt | None = None
        records: list[IdentificationEvidenceRecord] = []
        provider_deferred = False
        if stored is None and self._provider is not None:
            try:
                candidate = await self._provider.get_album_candidate(
                    str(identity["release_group_mbid"]),
                    len(context["tracks"]),
                    RequestPriority.BACKGROUND_SYNC,
                )
            except ExternalServiceError:
                candidate = None
                provider_deferred = True
            if candidate is not None:
                tracks = [_to_grouping_track(row) for row in context["tracks"]]
                for track, row in zip(tracks, context["tracks"], strict=True):
                    cached = await self._store.get_fingerprint_outcome(
                        track.local_track_id,
                        str(row["stat_revision"]),
                        FINGERPRINTER_VERSION,
                    )
                    if (
                        cached is not None
                        and cached.state == "matched"
                        and cached.recording_mbid
                    ):
                        track.recording_mbid = cached.recording_mbid
                evaluated = self._evidence.evaluate_candidate(tracks, candidate)
                attempt_id = str(uuid.uuid4())
                evidence_id = str(uuid.uuid4())
                revisions = album_input_revisions(context["tracks"])
                attempt = IdentificationAttempt(
                    id=attempt_id,
                    local_album_id=album_id,
                    trigger="repair_audit",
                    input_tag_revision=revisions[0],
                    input_file_revision=revisions[1],
                    input_policy_revision=revisions[2],
                    matcher_version=MATCHER_VERSION,
                    state=(
                        "identified"
                        if evaluated.reason_code == "SUPPORTED"
                        else "contradictory"
                    ),
                    terminal_reason_code=evaluated.reason_code,
                    selected_candidate_key=_candidate_key(evaluated),
                    candidate_count=1,
                    started_at=float(work["updated_at"]),
                    completed_at=float(work["updated_at"]),
                )
                stored = IdentificationEvidenceRecord(
                    id=evidence_id,
                    attempt_id=attempt_id,
                    candidate_key=_candidate_key(evaluated),
                    evidence=evaluated,
                    created_at=float(work["updated_at"]),
                )
                records = [stored]
        if stored is None:
            return (
                self._finding(
                    job_id,
                    work,
                    "unverifiable",
                    "PROVIDER_DEFERRED"
                    if provider_deferred
                    else "EVIDENCE_UNAVAILABLE",
                    False,
                    identity_revision=int(identity["row_revision"]),
                ),
                None,
                [],
            )
        supported = sum(
            item.classification == "supported"
            for item in stored.evidence.track_evidence
        )
        contradictory = sum(
            item.classification == "contradictory"
            for item in stored.evidence.track_evidence
        )
        complete = not stored.evidence.unmatched_expected_tracks
        safe = complete and (supported == 0 or contradictory > 0)
        if safe:
            finding_code = "safe_detach"
            reason = "ZERO_SUPPORT" if supported == 0 else "HARD_CONTRADICTION"
        elif stored.evidence.reason_code in {
            "ACCEPTED",
            "SUPPORTED",
            "SUPPORTED_EMBEDDED_IDS",
        }:
            finding_code = "valid"
            reason = "CURRENT_IDENTITY_PASSES"
        else:
            finding_code = "needs_review"
            reason = "NON_TERMINAL_SAFETY_CONCERN"
        return (
            self._finding(
                job_id,
                work,
                finding_code,
                reason,
                safe,
                evidence_id=stored.id,
                identity_revision=int(identity["row_revision"]),
            ),
            attempt,
            records,
        )

    @staticmethod
    def _finding(
        job_id: str,
        work: dict,
        finding_code: str,
        reason_code: str,
        apply_eligible: bool,
        *,
        evidence_id: str | None = None,
        identity_revision: int | None = None,
    ) -> RepairFinding:
        return RepairFinding(
            id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{job_id}:{work['local_album_id']}:{finding_code}",
                )
            ),
            local_album_id=str(work["local_album_id"]),
            expected_album_revision=int(work["expected_subject_revision"]),
            expected_identity_revision=identity_revision,
            finding_code=finding_code,
            reason_code=reason_code,
            confidence="complete" if apply_eligible else "bounded",
            apply_eligible=apply_eligible,
            evidence_id=evidence_id,
        )
