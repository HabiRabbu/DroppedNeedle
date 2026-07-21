from __future__ import annotations

import time
import uuid

from core.exceptions import ExternalServiceError, ResourceNotFoundError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from infrastructure.queue.priority_queue import RequestPriority
from models.identification import IdentificationAttempt, IdentificationEvidenceRecord
from models.library_contribution import ContributionRecord
from repositories.protocols.musicbrainz import MusicBrainzRepositoryProtocol
from services.native.album_evidence_engine import MATCHER_VERSION
from services.native.identification_revisions import album_input_revisions
from services.native.library_contribution_service import LibraryContributionService

LEASE_SECONDS = 90.0
MAX_AUTOMATIC_WINDOW_SECONDS = 2 * 60 * 60
MAX_AUTOMATIC_ATTEMPTS = 10
MAX_RETRY_SECONDS = 10 * 60
CLEANUP_INTERVAL_SECONDS = 60 * 60


class LibraryContributionVerificationWorker:
    def __init__(
        self,
        store: NativeLibraryStore,
        contribution_service: LibraryContributionService,
        musicbrainz_repository: MusicBrainzRepositoryProtocol,
    ) -> None:
        self._store = store
        self._contributions = contribution_service
        self._musicbrainz = musicbrainz_repository
        self._next_cleanup_at = 0.0

    async def recover(self, *, now: float | None = None) -> int:
        timestamp = time.time() if now is None else now
        recovered = await self._store.recover_library_contribution_verification_leases(
            now=timestamp
        )
        if timestamp >= self._next_cleanup_at:
            await self._contributions.purge_expired_provider_data(now=timestamp)
            await self._store.clean_library_contribution_records(now=timestamp)
            self._next_cleanup_at = timestamp + CLEANUP_INTERVAL_SECONDS
        return recovered

    async def claim(self, worker_id: str, *, now: float | None = None) -> dict | None:
        return await self._store.claim_library_contribution_verification(
            worker_id=worker_id,
            now=time.time() if now is None else now,
            lease_seconds=LEASE_SECONDS,
        )

    async def run_once(self, worker_id: str, *, now: float | None = None) -> str | None:
        timestamp = time.time() if now is None else now
        job = await self.claim(worker_id, now=timestamp)
        if job is None:
            return None
        return await self.run_claimed(job, worker_id, now=timestamp)

    async def run_claimed(
        self,
        job: dict,
        worker_id: str,
        *,
        now: float | None = None,
    ) -> str:
        timestamp = time.time() if now is None else now
        job_revision = await self._store.heartbeat_library_contribution_verification(
            job_id=str(job["id"]),
            worker_id=worker_id,
            expected_row_revision=int(job["row_revision"]),
            now=timestamp,
            lease_seconds=LEASE_SECONDS,
        )
        contribution_id = str(job["contribution_id"])
        try:
            contribution = await self._contributions.get(contribution_id)
        except ResourceNotFoundError:
            return "subject_missing"
        if contribution.state != "verifying" or not contribution.result_release_mbid:
            return "no_longer_verifying"

        try:
            verified = await self._musicbrainz.get_release_for_verification(
                contribution.result_release_mbid,
                priority=RequestPriority.BACKGROUND_SYNC,
                bypass_cache=True,
            )
        except ExternalServiceError:
            return await self._retry_or_review(
                job,
                job_revision=job_revision,
                worker_id=worker_id,
                contribution=contribution,
                failure_code="MUSICBRAINZ_TEMPORARILY_UNAVAILABLE",
                now=timestamp,
            )
        if verified is None:
            return await self._retry_or_review(
                job,
                job_revision=job_revision,
                worker_id=worker_id,
                contribution=contribution,
                failure_code="MUSICBRAINZ_RELEASE_NOT_PROPAGATED",
                now=timestamp,
            )
        if verified.release_mbid != contribution.result_release_mbid:
            return await self._finish_without_candidate(
                job,
                job_revision=job_revision,
                worker_id=worker_id,
                contribution=contribution,
                failure_code="RETURNED_RELEASE_MISMATCH",
                now=timestamp,
            )

        decision, context = await self._contributions.build_attachment_evidence(
            contribution, verified
        )
        raw_tracks: list[dict] = context["tracks"]
        tag_revision, file_revision, policy_revision = album_input_revisions(raw_tracks)
        attempt_id = str(uuid.uuid4())
        evidence = [
            IdentificationEvidenceRecord(
                id=str(uuid.uuid4()),
                attempt_id=attempt_id,
                candidate_key=(
                    f"{candidate.release_group_mbid}:{candidate.release_mbid or ''}"
                ),
                evidence=candidate,
                created_at=timestamp,
            )
            for candidate in decision.candidates
        ]
        attempt = IdentificationAttempt(
            id=attempt_id,
            local_album_id=contribution.local_album_id,
            trigger="contribution_submission",
            requested_by_user_id=job.get("requested_by_user_id"),
            input_tag_revision=tag_revision,
            input_file_revision=file_revision,
            input_policy_revision=policy_revision,
            matcher_version=MATCHER_VERSION,
            state=decision.outcome,
            terminal_reason_code=decision.reason_code,
            selected_candidate_key=decision.selected_candidate_key,
            candidate_count=len(decision.candidates),
            started_at=timestamp,
            completed_at=timestamp,
        )
        result = await self._store.finish_library_contribution_verification(
            job_id=str(job["id"]),
            worker_id=worker_id,
            expected_job_revision=job_revision,
            expected_contribution_revision=contribution.row_revision,
            expected_album_revision=int(context["album"]["row_revision"]),
            attempt=attempt,
            evidence=evidence,
            outcome=(
                "identified" if decision.outcome == "identified" else "needs_review"
            ),
            failure_code=(
                None if decision.outcome == "identified" else decision.reason_code
            ),
            now=timestamp,
        )
        if result == "linked":
            await self._contributions.purge_provider_data(
                contribution.id, now=timestamp
            )
            await self._contributions.invalidate_catalog_cache()
        return result

    async def _retry_or_review(
        self,
        job: dict,
        *,
        job_revision: int,
        worker_id: str,
        contribution: ContributionRecord,
        failure_code: str,
        now: float,
    ) -> str:
        received_at = contribution.result_received_at or now
        attempts = int(job["attempt_count"])
        if (
            attempts < MAX_AUTOMATIC_ATTEMPTS
            and now - received_at < MAX_AUTOMATIC_WINDOW_SECONDS
        ):
            delay = min(MAX_RETRY_SECONDS, 15 * (2 ** min(attempts - 1, 6)))
            await self._store.retry_library_contribution_verification(
                job_id=str(job["id"]),
                worker_id=worker_id,
                expected_row_revision=job_revision,
                failure_code=failure_code,
                not_before=now + delay,
                now=now,
            )
            return "retry_scheduled"
        return await self._finish_without_candidate(
            job,
            job_revision=job_revision,
            worker_id=worker_id,
            contribution=contribution,
            failure_code=failure_code,
            now=now,
        )

    async def _finish_without_candidate(
        self,
        job: dict,
        *,
        job_revision: int,
        worker_id: str,
        contribution: ContributionRecord,
        failure_code: str,
        now: float,
    ) -> str:
        context = await self._store.get_album_identification_context(
            contribution.local_album_id
        )
        if context is None:
            return "subject_missing"
        tag_revision, file_revision, policy_revision = album_input_revisions(
            context["tracks"]
        )
        attempt = IdentificationAttempt(
            id=str(uuid.uuid4()),
            local_album_id=contribution.local_album_id,
            trigger="contribution_submission",
            requested_by_user_id=job.get("requested_by_user_id"),
            input_tag_revision=tag_revision,
            input_file_revision=file_revision,
            input_policy_revision=policy_revision,
            matcher_version=MATCHER_VERSION,
            state="needs_review",
            terminal_reason_code=failure_code,
            candidate_count=0,
            started_at=now,
            completed_at=now,
        )
        return await self._store.finish_library_contribution_verification(
            job_id=str(job["id"]),
            worker_id=worker_id,
            expected_job_revision=job_revision,
            expected_contribution_revision=contribution.row_revision,
            expected_album_revision=int(context["album"]["row_revision"]),
            attempt=attempt,
            evidence=[],
            outcome="needs_review",
            failure_code=failure_code,
            now=now,
        )
