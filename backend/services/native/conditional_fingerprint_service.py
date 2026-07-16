"""Revision-keyed, conditional fingerprinting outside filesystem scans."""

from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.audio import FingerprintResult
from models.identification import FingerprintOutcome

FINGERPRINTER_VERSION = "fpcalc-acoustid-v1"
MAX_CONCURRENT_FINGERPRINTS = 2
TRANSIENT_RETRY_SECONDS = 60.0


class FingerprinterProtocol(Protocol):
    def is_enabled(self) -> bool: ...

    async def generate_fingerprint(self, path: Path) -> tuple[str, int]: ...

    async def lookup_fingerprint(
        self, fingerprint: str, duration: int
    ) -> FingerprintResult: ...


class ConditionalFingerprintService:
    def __init__(
        self,
        store: NativeLibraryStore,
        fingerprinter: FingerprinterProtocol,
    ) -> None:
        self._store = store
        self._fingerprinter = fingerprinter
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_FINGERPRINTS)

    async def fingerprint_if_needed(
        self,
        *,
        local_track_id: str,
        path: Path,
        stat_revision: str,
        needed: bool,
        now: float | None = None,
        checkpoint: Callable[[], Awaitable[bool]] | None = None,
    ) -> FingerprintOutcome | None:
        if not needed:
            return None
        if checkpoint is not None and not await checkpoint():
            return None
        cached = await self._store.get_fingerprint_outcome(
            local_track_id, stat_revision, FINGERPRINTER_VERSION
        )
        timestamp = time.time() if now is None else now
        if cached is not None and (
            cached.state not in ("failed", "deferred")
            or cached.retry_after is None
            or cached.retry_after > timestamp
        ):
            return cached
        if not self._fingerprinter.is_enabled():
            disabled = FingerprintOutcome(
                id=cached.id if cached is not None else str(uuid.uuid4()),
                local_track_id=local_track_id,
                stat_revision=stat_revision,
                fingerprinter_version=FINGERPRINTER_VERSION,
                state="disabled",
                first_attempt_at=(cached.first_attempt_at if cached else timestamp),
                last_attempt_at=timestamp,
            )
            await self._store.record_fingerprint_outcome(disabled)
            return await self._store.get_fingerprint_outcome(
                local_track_id, stat_revision, FINGERPRINTER_VERSION
            )
        if cached is not None and cached.fingerprint and cached.duration_seconds:
            fingerprint = cached.fingerprint
            duration = int(cached.duration_seconds)
        else:
            try:
                async with self._semaphore:
                    (
                        fingerprint,
                        duration,
                    ) = await self._fingerprinter.generate_fingerprint(path)
            except (OSError, ValueError, TimeoutError, subprocess.SubprocessError):
                failed = FingerprintOutcome(
                    id=cached.id if cached is not None else str(uuid.uuid4()),
                    local_track_id=local_track_id,
                    stat_revision=stat_revision,
                    fingerprinter_version=FINGERPRINTER_VERSION,
                    state="failed",
                    failure_code="FINGERPRINT_LOCAL_FAILURE",
                    first_attempt_at=(cached.first_attempt_at if cached else timestamp),
                    last_attempt_at=timestamp,
                )
                await self._store.record_fingerprint_outcome(failed)
                return await self._store.get_fingerprint_outcome(
                    local_track_id, stat_revision, FINGERPRINTER_VERSION
                )
            await self._store.record_fingerprint_outcome(
                FingerprintOutcome(
                    id=cached.id if cached is not None else str(uuid.uuid4()),
                    local_track_id=local_track_id,
                    stat_revision=stat_revision,
                    fingerprinter_version=FINGERPRINTER_VERSION,
                    state="deferred",
                    fingerprint=fingerprint,
                    duration_seconds=float(duration),
                    failure_code="LOOKUP_PENDING",
                    first_attempt_at=(cached.first_attempt_at if cached else timestamp),
                    last_attempt_at=timestamp,
                    retry_after=timestamp,
                )
            )
            if checkpoint is not None and not await checkpoint():
                return await self._store.get_fingerprint_outcome(
                    local_track_id, stat_revision, FINGERPRINTER_VERSION
                )
        result = await self._fingerprinter.lookup_fingerprint(fingerprint, duration)
        if checkpoint is not None and not await checkpoint():
            return await self._store.get_fingerprint_outcome(
                local_track_id, stat_revision, FINGERPRINTER_VERSION
            )
        state_by_status = {
            "pass": "matched",
            "skip": "no_match",
            "fail": "no_match",
            "disabled": "disabled",
            "error": "failed",
        }
        state = state_by_status[result.status]
        outcome = FingerprintOutcome(
            id=cached.id if cached is not None else str(uuid.uuid4()),
            local_track_id=local_track_id,
            stat_revision=stat_revision,
            fingerprinter_version=FINGERPRINTER_VERSION,
            state=state,
            fingerprint=fingerprint,
            duration_seconds=float(duration),
            recording_mbid=result.recording_id,
            release_group_ids=result.release_group_ids,
            score=result.score,
            failure_code=(
                "FINGERPRINT_TRANSIENT_FAILURE" if state == "failed" else None
            ),
            attempt_count=(cached.attempt_count + 1 if cached is not None else 1),
            first_attempt_at=(
                cached.first_attempt_at if cached is not None else timestamp
            ),
            last_attempt_at=timestamp,
            retry_after=(
                timestamp + TRANSIENT_RETRY_SECONDS if state == "failed" else None
            ),
        )
        await self._store.record_fingerprint_outcome(outcome)
        return await self._store.get_fingerprint_outcome(
            local_track_id, stat_revision, FINGERPRINTER_VERSION
        )
