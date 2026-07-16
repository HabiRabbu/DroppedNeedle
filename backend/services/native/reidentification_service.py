"""Tracked explicit re-identification creation and queue arbitration."""

from __future__ import annotations

import time
import uuid

from core.exceptions import ResourceNotFoundError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_work import OperationJob
from services.native.identification_queue_service import IdentificationQueueService
from services.native.identification_revisions import album_input_revisions


class ReidentificationService:
    def __init__(self, store: NativeLibraryStore) -> None:
        self._store = store

    async def create_or_coalesce(
        self,
        album_id: str,
        requested_by_user_id: str,
        *,
        expected_album_revision: int | None = None,
        expected_input_revision: str | None = None,
        one_off_local_metadata: bool = False,
        idempotency_key: str | None = None,
        review_id: str | None = None,
        expected_review_revision: int | None = None,
        now: float | None = None,
    ) -> dict:
        timestamp = time.time() if now is None else now
        context = await self._store.get_album_identification_context(album_id)
        if context is None:
            raise ResourceNotFoundError(f"Album not found: {album_id}")
        revisions = album_input_revisions(context["tracks"])
        input_revision = ":".join(revisions)
        if (
            expected_input_revision is not None
            and expected_input_revision != input_revision
        ):
            from core.exceptions import StaleRevisionError

            raise StaleRevisionError(
                "The album inputs changed before re-identification started."
            )
        album_revision = int(context["album"]["row_revision"])
        if (
            expected_album_revision is not None
            and expected_album_revision != album_revision
        ):
            from core.exceptions import StaleRevisionError

            raise StaleRevisionError(
                "The album changed before re-identification started."
            )
        idempotency_key = idempotency_key or (
            f"explicit_reidentification:{album_id}:{input_revision}"
        )
        existing = await self._store.get_operation_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        job_id = str(uuid.uuid4())
        return await self._store.create_reidentification_operation(
            OperationJob(
                id=job_id,
                kind="explicit_reidentification",
                requested_by_user_id=requested_by_user_id,
                expected_work_count=1,
                idempotency_key=idempotency_key,
                created_at=timestamp,
            ),
            local_album_id=album_id,
            expected_album_revision=album_revision,
            expected_input_revision=input_revision,
            one_off_local_metadata=one_off_local_metadata,
            review_id=review_id,
            expected_review_revision=expected_review_revision,
        )


class IdentificationWorkArbiter:
    """Always offers explicit administrator work before automatic work."""

    def __init__(
        self, store: NativeLibraryStore, automatic: IdentificationQueueService
    ) -> None:
        self._store = store
        self._automatic = automatic

    async def claim(self, worker_id: str, *, now: float) -> tuple[str, dict] | None:
        explicit = await self._store.claim_operation_job(
            worker_id,
            now=now,
            lease_seconds=60.0,
            kind="explicit_reidentification",
        )
        if explicit is not None:
            return "explicit_reidentification", explicit
        automatic = await self._automatic.claim(worker_id, now=now)
        return ("automatic", automatic) if automatic is not None else None
