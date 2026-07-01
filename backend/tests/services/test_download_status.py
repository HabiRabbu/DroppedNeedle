"""DownloadStatus state-machine tests (ArrRebuild step 5).

The enum is the single source of truth for task statuses; these pin its values, the
terminal set, the legal-transition map, and - critically - that the PERSISTED members
stay byte-identical to the ``download_tasks`` CHECK constraint so the two can't drift.
"""

import re
from pathlib import Path

from services.native.acquisition.status import (
    LEGAL_TRANSITIONS,
    PERSISTED,
    TERMINAL,
    DownloadStatus,
    can_transition,
    is_terminal,
)


def test_strenum_members_are_their_wire_strings():
    # StrEnum => each member IS its DB/SSE/frontend string (drop-in, wire-identical).
    assert DownloadStatus.COMPLETED == "completed"
    assert f"{DownloadStatus.FAILED}" == "failed"
    assert DownloadStatus.AWAITING_REVIEW == "awaiting_review"
    # usable as a dict key interchangeably with the string
    assert {"completed": 1}[DownloadStatus.COMPLETED] == 1


def test_terminal_set():
    assert TERMINAL == {
        DownloadStatus.COMPLETED, DownloadStatus.PARTIAL,
        DownloadStatus.FAILED, DownloadStatus.CANCELLED,
    }
    assert is_terminal(DownloadStatus.COMPLETED) and is_terminal("failed")
    assert not is_terminal(DownloadStatus.DOWNLOADING)
    assert not is_terminal(DownloadStatus.RETRYING)  # transient, not terminal


def test_transient_statuses_are_not_persisted():
    # retrying / awaiting_review are SSE-only and must NOT be in the persisted set.
    assert DownloadStatus.RETRYING not in PERSISTED
    assert DownloadStatus.AWAITING_REVIEW not in PERSISTED
    assert PERSISTED == set(DownloadStatus) - {DownloadStatus.RETRYING, DownloadStatus.AWAITING_REVIEW}


def test_legal_transitions():
    assert can_transition(DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING)
    assert can_transition(DownloadStatus.DOWNLOADING, DownloadStatus.PROCESSING)
    assert can_transition(DownloadStatus.PROCESSING, DownloadStatus.COMPLETED)
    assert can_transition(DownloadStatus.RETRYING, DownloadStatus.DOWNLOADING)
    # terminal states have no outgoing transitions (a retry creates a NEW task)
    assert not can_transition(DownloadStatus.COMPLETED, DownloadStatus.DOWNLOADING)
    assert DownloadStatus.COMPLETED not in LEGAL_TRANSITIONS


def test_persisted_set_matches_the_store_check_constraint():
    # The DownloadStatus.PERSISTED members are the authoritative vocabulary; the
    # download_tasks CHECK must list EXACTLY the same set (mirrored, can't drift).
    store_src = Path(__file__).resolve().parents[2] / "infrastructure" / "persistence" / "download_store.py"
    text = store_src.read_text()
    # other tables (e.g. held_imports) also have a status CHECK, so pick the download_tasks
    # one by the vocabulary it lists ('downloading' is unique to it).
    checks = re.findall(r"CHECK\(status IN \(([^)]*)\)\)", text)
    task_check = next((c for c in checks if "downloading" in c), None)
    assert task_check, "could not find the download_tasks status CHECK constraint"
    check_values = set(re.findall(r"'([a-z_]+)'", task_check))
    assert check_values == {s.value for s in PERSISTED}
