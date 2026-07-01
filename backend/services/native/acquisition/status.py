"""Explicit download-task state (ArrRebuild step 5).

Lidarr reconstructs TrackedDownload state implicitly each poll; we make the states
explicit and typed. ``DownloadStatus`` is a ``StrEnum`` so each member IS its wire
string — it's drop-in everywhere the bare strings were used (DB column, SSE payloads,
the frontend contract are all byte-identical) while giving one typed source of truth.

The PERSISTED members are mirrored in the ``download_tasks.status`` CHECK constraint
(``infrastructure/persistence/download_store.py``); keep the two in sync. ``RETRYING`` /
``AWAITING_REVIEW`` are TRANSIENT UI signals published over SSE only — they are never
written to the DB, so they are deliberately NOT in the CHECK.
"""

from enum import StrEnum


class DownloadStatus(StrEnum):
    # --- persisted task statuses (mirror the download_tasks CHECK) ---
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # --- transient, SSE-only (never persisted; NOT in the CHECK) ---
    RETRYING = "retrying"
    AWAITING_REVIEW = "awaiting_review"


# Written to the DB → must be a subset of the download_tasks CHECK vocabulary.
PERSISTED: frozenset[DownloadStatus] = frozenset({
    DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.PROCESSING,
    DownloadStatus.COMPLETED, DownloadStatus.PARTIAL, DownloadStatus.FAILED,
    DownloadStatus.CANCELLED,
})

# A task in one of these has reached a final state (no further automatic transition; a
# retry creates a NEW task). Drives the terminal-transition path + request reconcile.
TERMINAL: frozenset[DownloadStatus] = frozenset({
    DownloadStatus.COMPLETED, DownloadStatus.PARTIAL, DownloadStatus.FAILED,
    DownloadStatus.CANCELLED,
})


def is_terminal(status: str) -> bool:
    """True for a final status (StrEnum compares equal to its wire string, so a bare
    ``"completed"`` works here too)."""
    return status in TERMINAL


# The explicit state machine, for documentation + optional validation. Not enforced at
# runtime (a wrongly-narrow map would reject a legitimate flow); ``can_transition`` is
# available for callers/tests that want to assert legality.
LEGAL_TRANSITIONS: dict[DownloadStatus, frozenset[DownloadStatus]] = {
    DownloadStatus.QUEUED: frozenset({
        DownloadStatus.DOWNLOADING, DownloadStatus.AWAITING_REVIEW,
        DownloadStatus.FAILED, DownloadStatus.CANCELLED,
    }),
    DownloadStatus.DOWNLOADING: frozenset({
        DownloadStatus.PROCESSING, DownloadStatus.RETRYING,
        DownloadStatus.FAILED, DownloadStatus.CANCELLED,
    }),
    DownloadStatus.PROCESSING: frozenset({
        DownloadStatus.COMPLETED, DownloadStatus.PARTIAL, DownloadStatus.RETRYING,
        DownloadStatus.FAILED, DownloadStatus.CANCELLED,
    }),
    DownloadStatus.RETRYING: frozenset({
        DownloadStatus.DOWNLOADING, DownloadStatus.PROCESSING,
        DownloadStatus.FAILED, DownloadStatus.CANCELLED,
    }),
    DownloadStatus.AWAITING_REVIEW: frozenset({
        DownloadStatus.DOWNLOADING, DownloadStatus.FAILED, DownloadStatus.CANCELLED,
    }),
}


def can_transition(from_status: DownloadStatus, to_status: DownloadStatus) -> bool:
    """Whether ``from_status -> to_status`` is a defined transition. Terminal states have
    no outgoing transitions (a retry creates a new task)."""
    return to_status in LEGAL_TRANSITIONS.get(from_status, frozenset())
