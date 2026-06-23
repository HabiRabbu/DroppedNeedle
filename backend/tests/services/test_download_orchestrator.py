"""DownloadOrchestrator lifecycle tests (task-046).

Real DownloadStore (status transitions, search-job round-trip, quarantine) + real
SSEPublisher/ManifestCodec; the scorer and FileProcessor are mocked so each branch
(auto-pick, manual park, no-match, enqueue failure, partial, quarantine, cancel,
retry, startup_resume) is exercised deterministically. The full real import is
covered by the E2E gate (tests/infrastructure/test_e2e_download.py)."""

import asyncio
import sqlite3
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import (
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)
from core.task_registry import TaskRegistry
from infrastructure.persistence.download_store import DownloadStore
from infrastructure.sse_publisher import SSEPublisher
from models.common import ServiceStatus
from models.download import ScoredCandidate
from models.download_manifest import DownloadManifest, ExpectedFile, ManifestCodec
from repositories.protocols.download_client import DownloadSearchResult, DownloadTaskStatus, TaskRef
from services.native.download_orchestrator import DownloadOrchestrator, _Cancelled
from services.native.file_processor import FileFailure, ProcessResult


def _write_manifest(orch, task_id, filenames, username="peer"):
    manifest = DownloadManifest(
        task_id=task_id, source_username=username, release_group_mbid="rg-1",
        artist_name="A", album_title="B", naming_template=_TEMPLATE,
        target_files=[ExpectedFile(filename=f, size=1) for f in filenames],
    )
    d = orch._staging / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_bytes(orch._manifest_codec.encode(manifest))

_TEMPLATE = "{albumartist}/{album} ({year})/{disc:02d}{track:02d} {title}.{ext}"


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT, role TEXT)"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, username, role) VALUES (?, ?, ?)",
            [("user-a", "alice", "user"), ("user-b", "bob", "user")],
        )
        conn.commit()
    finally:
        conn.close()


def _candidate(score: float, *, files: int = 1) -> ScoredCandidate:
    results = [
        DownloadSearchResult(
            username="peer", filename=f"A/{i:02d}.flac", parent_directory="A",
            size=100, extension="flac", duration=None,
        )
        for i in range(1, files + 1)
    ]
    return ScoredCandidate(
        username="peer", parent_directory="A", files=results,
        coherence=score, file_confidence=score, final_score=score,
        tier="auto" if score >= 0.7 else "manual",
    )


class _StubClient:
    def __init__(self) -> None:
        self.enqueue = AsyncMock(return_value=TaskRef(username="peer", filenames=["A/01.flac"]))
        self.cancel = AsyncMock(return_value=True)
        self.get_status = AsyncMock(
            return_value=DownloadTaskStatus(
                task_id="", status="completed", files_total=1, files_completed=1,
                bytes_total=0, bytes_downloaded=0, progress_percent=100.0,
            )
        )

    @property
    def client_name(self) -> str:
        return "stub"

    def is_configured(self) -> bool:
        return True

    async def health_check(self) -> ServiceStatus:
        return ServiceStatus(status="ok")

    async def search_album(self, *a, **k):
        return []

    async def search_track(self, *a, **k):
        return []

    async def get_file_path(self, username, remote_filename):
        return Path("/fake") / remote_filename


def _build(tmp_path: Path, *, client=None, scorer_result=None, track_result=None, fp_result=None):
    db_path = tmp_path / "library.db"
    store = DownloadStore(db_path=db_path, write_lock=threading.Lock())
    _seed_auth_users(db_path)

    scorer = MagicMock()
    scorer.rank = AsyncMock(return_value=scorer_result if scorer_result is not None else [])
    track_matcher = MagicMock()
    track_matcher.match = AsyncMock(return_value=track_result)
    file_processor = MagicMock()
    file_processor.process_downloaded = AsyncMock(
        return_value=fp_result if fp_result is not None else ProcessResult(succeeded=[], failed=[])
    )

    orch = DownloadOrchestrator(
        client=client or _StubClient(),
        download_store=store,
        file_processor=file_processor,
        library_manager=MagicMock(),
        scorer=scorer,
        track_matcher=track_matcher,
        manifest_codec=ManifestCodec(),
        event_bus=SSEPublisher(),
        staging_path=tmp_path / "staging",
        naming_template=_TEMPLATE,
        poll_interval=0.0,
        auto_accept_threshold=0.7,
        manual_threshold=0.5,
    )
    return store, orch, file_processor


async def _new_task(store, **overrides):
    kwargs = dict(
        user_id="user-a", download_type="album", release_group_mbid="rg-1",
        artist_name="Artist", album_title="Album", year=2020, track_count=1,
    )
    kwargs.update(overrides)
    return await store.create_task(**kwargs)


@pytest.mark.asyncio
async def test_process_task_autopicks_and_completes(tmp_path: Path):
    client = _StubClient()
    store, orch, fp = _build(
        tmp_path, client=client, scorer_result=[_candidate(0.9)],
        fp_result=ProcessResult(succeeded=[str(tmp_path / "lib" / "a.flac")], failed=[]),
    )
    task = await _new_task(store)

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final.status == "completed"
    fp.process_downloaded.assert_awaited_once()
    client.enqueue.assert_awaited_once()
    # post-import transfer cleanup happens exactly once
    client.cancel.assert_awaited_once()
    # manifest staging dir cleaned
    assert not (tmp_path / "staging" / task.id).exists()
    # (AUD-8) auto-pick moved the search job to 'matched'
    job = await store.get_search_job(final.search_job_id)
    assert job.status == "matched"


@pytest.mark.asyncio
async def test_process_task_parks_for_manual_review(tmp_path: Path):
    client = _StubClient()
    store, orch, _fp = _build(tmp_path, client=client, scorer_result=[_candidate(0.6)])
    task = await _new_task(store)

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final.status == "queued"           # parked, not downloading
    assert final.search_job_id is not None
    assert final.candidate_index is None      # nothing picked yet
    client.enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_task_no_match_fails(tmp_path: Path):
    store, orch, _fp = _build(tmp_path, scorer_result=[])
    task = await _new_task(store)

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final.status == "failed"
    assert "No matching candidate" in (final.error_message or "")


@pytest.mark.asyncio
async def test_enqueue_failure_marks_failed_without_quarantine(tmp_path: Path):
    client = _StubClient()
    client.enqueue = AsyncMock(side_effect=RuntimeError("boom"))
    store, orch, _fp = _build(tmp_path, client=client, scorer_result=[_candidate(0.9)])
    task = await _new_task(store)

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final.status == "failed"
    assert final.error_message == "enqueue failed"   # sanitized (AUD-11)
    assert await store.load_quarantine_set() == set()


@pytest.mark.asyncio
async def test_partial_quarantines_each_failed_file(tmp_path: Path):
    client = _StubClient()
    store, orch, _fp = _build(
        tmp_path, client=client, scorer_result=[_candidate(0.9, files=2)],
        fp_result=ProcessResult(
            succeeded=[str(tmp_path / "lib" / "a.flac")],
            failed=[FileFailure(filename="A/02.flac", reason="duration_mismatch")],
        ),
    )
    task = await _new_task(store)

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final.status == "partial"
    assert ("peer", "A/02.flac") in await store.load_quarantine_set()
    client.cancel.assert_awaited_once()   # some succeeded -> cleanup runs


@pytest.mark.asyncio
async def test_all_failed_marks_failed_and_skips_cleanup(tmp_path: Path):
    client = _StubClient()
    store, orch, _fp = _build(
        tmp_path, client=client, scorer_result=[_candidate(0.9)],
        fp_result=ProcessResult(
            succeeded=[], failed=[FileFailure(filename="A/01.flac", reason="corrupt")]
        ),
    )
    task = await _new_task(store)

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final.status == "failed"
    assert final.error_message == "verification failed"
    client.cancel.assert_not_awaited()   # nothing imported -> leave transfers


@pytest.mark.asyncio
async def test_cancel_task_ownership(tmp_path: Path):
    store, orch, _fp = _build(tmp_path)
    task = await _new_task(store)

    with pytest.raises(ResourceNotFoundError):
        await orch.cancel_task("does-not-exist", "user-a", "user")
    with pytest.raises(PermissionDeniedError):
        await orch.cancel_task(task.id, "user-b", "user")

    await orch.cancel_task(task.id, "user-a", "user")
    final = await store.get_task(task.id)
    assert final.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_task_admin_can_cancel_others(tmp_path: Path):
    store, orch, _fp = _build(tmp_path)
    task = await _new_task(store)
    await orch.cancel_task(task.id, "admin-x", "admin")
    assert (await store.get_task(task.id)).status == "cancelled"


@pytest.mark.asyncio
async def test_retry_task_creates_new_clean_task(tmp_path: Path):
    store, orch, _fp = _build(tmp_path)
    orch.dispatch = MagicMock()   # don't run the new task in the background
    task = await _new_task(store, status="failed")

    new_id = await orch.retry_task(task.id, "user-a", "user")

    assert new_id != task.id
    new_task = await store.get_task(new_id)
    assert new_task.retry_count == 1
    assert new_task.status == "queued"
    orch.dispatch.assert_called_once_with(new_id)


@pytest.mark.asyncio
async def test_retry_task_rejects_non_retryable_state(tmp_path: Path):
    store, orch, _fp = _build(tmp_path)
    task = await _new_task(store, status="queued")
    with pytest.raises(ValidationError):
        await orch.retry_task(task.id, "user-a", "user")


@pytest.mark.asyncio
async def test_retry_task_ownership(tmp_path: Path):
    store, orch, _fp = _build(tmp_path)
    task = await _new_task(store, status="failed")
    with pytest.raises(ResourceNotFoundError):
        await orch.retry_task("missing", "user-a", "user")
    with pytest.raises(PermissionDeniedError):
        await orch.retry_task(task.id, "user-b", "user")


@pytest.mark.asyncio
async def test_startup_resume_redispatches_queued(tmp_path: Path):
    store, orch, _fp = _build(tmp_path)
    orch.dispatch = MagicMock()
    queued = await _new_task(store, status="queued")

    await orch.startup_resume()

    orch.dispatch.assert_called_once_with(queued.id)


@pytest.mark.asyncio
async def test_dispatch_safe_runner_sanitizes_unhandled_error(tmp_path: Path):
    """dispatch() runs the safe runner: a non-OrchestrationError is caught, the task
    is marked failed with a SANITIZED message (AUD-11), registered in TaskRegistry
    (AUD-3), and popped from _active_tasks on completion."""
    store, orch, _fp = _build(tmp_path)
    task = await _new_task(store)

    async def _boom(_tid):
        raise RuntimeError("raw boom detail")

    orch.process_task = _boom

    handle = orch.dispatch(task.id)
    assert TaskRegistry.get_instance().is_running(f"download-{task.id}")
    await handle

    final = await store.get_task(task.id)
    assert final.status == "failed"
    assert final.error_message == "download failed"  # sanitized, not "raw boom detail"
    assert task.id not in orch._active_tasks


@pytest.mark.asyncio
async def test_resume_single_task_completed(tmp_path: Path):
    store, orch, _fp = _build(
        tmp_path, fp_result=ProcessResult(succeeded=[str(tmp_path / "a.flac")], failed=[]),
    )
    task = await _new_task(store, status="downloading", source_username="peer")
    _write_manifest(orch, task.id, ["A/01.flac"])

    await orch._resume_single_task(task.id)

    assert (await store.get_task(task.id)).status == "completed"


@pytest.mark.asyncio
async def test_resume_single_task_transfer_lost(tmp_path: Path):
    client = _StubClient()
    client.get_status = AsyncMock(
        return_value=DownloadTaskStatus(
            task_id="", status="queued", files_total=1, files_completed=0,
            bytes_total=0, bytes_downloaded=0, progress_percent=0.0,
        )
    )
    store, orch, _fp = _build(tmp_path, client=client)
    task = await _new_task(store, status="downloading", source_username="peer")
    _write_manifest(orch, task.id, ["A/01.flac"])

    await orch._resume_single_task(task.id)

    final = await store.get_task(task.id)
    assert final.status == "failed"
    assert final.error_message == "Transfer lost during restart"


@pytest.mark.asyncio
async def test_poll_until_done_bails_on_out_of_band_cancel(tmp_path: Path):
    """HIGH-#1 regression: a cancel that set status='cancelled' while the poll loop
    is running stops the loop (raises _Cancelled) so the import can't proceed."""
    store, orch, _fp = _build(tmp_path)
    task = await _new_task(store, status="downloading", source_username="peer")
    _write_manifest(orch, task.id, ["A/01.flac"])
    await store.update_status(task.id, "cancelled")
    task = await store.get_task(task.id)

    with pytest.raises(_Cancelled):
        await orch._poll_until_done(task)


@pytest.mark.asyncio
async def test_startup_resume_tracks_handle_so_cancel_can_reach_it(tmp_path: Path):
    """HIGH-#1 regression: a resumed downloading task is tracked in _active_tasks so
    cancel_task can stop its live poll loop (previously only in TaskRegistry)."""
    store, orch, _fp = _build(tmp_path)
    task = await _new_task(store, status="downloading", source_username="peer")
    started = asyncio.Event()

    async def _hang(_tid):
        started.set()
        await asyncio.sleep(3600)

    orch._resume_single_task = _hang
    await orch.startup_resume()
    await asyncio.wait_for(started.wait(), timeout=1.0)

    assert task.id in orch._active_tasks
    orch._active_tasks[task.id].cancel()
