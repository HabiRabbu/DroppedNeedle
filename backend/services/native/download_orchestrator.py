"""DownloadOrchestrator - the download lifecycle (Phase 7).

Owns search -> score -> auto-pick -> enqueue -> poll -> process -> notify (C1), plus
``cancel_task``, ``retry_task`` and ``startup_resume``. It speaks only the
``DownloadClientProtocol`` (never ``repositories/slskd`` directly) and never imports
``DownloadService`` (the dependency is one-way; no import cycle - A2).

Durable cross-task state lives in ``download_tasks`` + ``staging/{task_id}/
manifest.json``; the audio itself is written by slskd into its own download dir
(C4) and MOVED into the library by ``FileProcessor``. The only in-memory state is
``_active_tasks`` (live ``asyncio.Task`` handles for prompt cancel), rebuilt by
``startup_resume`` - it holds no authoritative data, so the class is ``@singleton``.
"""

import asyncio
import logging
import shutil
import time
from pathlib import Path

from core.exceptions import (
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)
from core.task_registry import TaskRegistry
from infrastructure.persistence.download_store import DownloadStore
from infrastructure.sse_publisher import SSEPublisher
from models.download import TargetTrack
from models.download_manifest import DownloadManifest, ExpectedFile, ManifestCodec
from repositories.protocols.download_client import (
    DownloadClientProtocol,
    DownloadFileRef,
    TaskRef,
)
from services.native.album_preflight_scorer import AlbumPreflightScorer
from services.native.file_processor import QUARANTINE_REASONS, FileProcessor
from services.native.library_manager import LibraryManager
from services.native.track_matcher import TrackMatcher

logger = logging.getLogger(__name__)

# 6-hour ceiling on a single download's poll loop.
_POLL_DEADLINE_SECONDS = 3600 * 6


class OrchestrationError(Exception):
    """Module-internal control-flow signal (enqueue/poll/timeout failures). Always
    caught inside the class; its message is a curated, sanitized string safe to
    persist/SSE (AUD-11)."""


class _Cancelled(Exception):
    """Internal signal: the task was cancelled out-of-band (by cancel_task) while a
    poll loop was running. Caught by process_task / _resume_single_task, which return
    without overwriting the already-set 'cancelled' status."""


def _user_error_message(exc: Exception) -> str:
    """AUD-11: map an exception to a small fixed set of user-facing strings. Raw
    ``str(exc)`` for arbitrary exceptions is never returned (logs only)."""
    if isinstance(exc, OrchestrationError):
        return str(exc)
    return "download failed"


def _basename(filename: str) -> str:
    """Last path segment (slskd filenames use backslashes); log basenames not full
    peer paths to keep log lines free of identifying directory structure."""
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _log_task_exception(task: "asyncio.Task") -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("Background download task failed: %s", exc, exc_info=exc)


class DownloadOrchestrator:
    def __init__(
        self,
        client: DownloadClientProtocol,
        download_store: DownloadStore,
        file_processor: FileProcessor,
        library_manager: LibraryManager,
        scorer: AlbumPreflightScorer,
        track_matcher: TrackMatcher,
        manifest_codec: ManifestCodec,
        event_bus: SSEPublisher,
        staging_path: Path,
        naming_template: str,
        poll_interval: float = 2.0,
        auto_accept_threshold: float = 0.70,
        manual_threshold: float = 0.50,
    ) -> None:
        self._client = client
        self._store = download_store
        self._file_processor = file_processor
        self._library = library_manager
        self._scorer = scorer
        self._track_matcher = track_matcher
        self._manifest_codec = manifest_codec
        self._bus = event_bus
        self._staging = Path(staging_path)
        self._naming_template = naming_template
        self._poll_interval = poll_interval
        self._auto = auto_accept_threshold
        self._manual = manual_threshold
        self._active_tasks: dict[str, asyncio.Task] = {}

    def dispatch(self, task_id: str) -> "asyncio.Task":
        """Run ``process_task`` for ``task_id`` in the background (AUD-3): wrapped in
        the safe runner, registered in ``TaskRegistry`` so shutdown cancels it, and
        tracked in ``_active_tasks`` so ``cancel_task`` can stop the live poll loop."""
        task = asyncio.create_task(self._run_orchestrator_safely(task_id))
        self._active_tasks[task_id] = task
        task.add_done_callback(_log_task_exception)
        task.add_done_callback(lambda _t, _id=task_id: self._active_tasks.pop(_id, None))
        TaskRegistry.get_instance().register(f"download-{task_id}", task)
        return task

    async def _run_orchestrator_safely(self, task_id: str) -> None:
        """Wrap ``process_task`` so an unhandled exception updates the task to
        ``failed`` (sanitized message, AUD-11) instead of vanishing into a
        fire-and-forget create_task."""
        try:
            await self.process_task(task_id)
        except Exception as exc:  # noqa: BLE001 - last line of defence for a bg task
            logger.exception("Unhandled exception in orchestrator task %s", task_id)
            try:
                user_msg = _user_error_message(exc)
                await self._store.update_status(task_id, "failed", error_message=user_msg)
                logger.info(
                    "download.failed",
                    extra={"task_id": task_id, "error_message": user_msg},
                )
                await self._bus.publish(
                    f"download:{task_id}", "complete",
                    {"status": "failed", "error": user_msg},
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to mark task %s failed after error", task_id)

    async def process_task(self, task_id: str) -> None:
        """Main lifecycle. Two entry shapes converge here: a direct request (no
        candidate linked -> search/score/auto-pick first) and a manual pick (a
        candidate already linked -> straight to enqueue)."""
        task = await self._store.get_task(task_id)
        if task is None:
            logger.error("Download task %s not found", task_id)
            return

        logger.info(
            "download.started",
            extra={
                "task_id": task.id,
                "user_id": task.user_id,
                "download_type": task.download_type,
                "release_group_mbid": task.release_group_mbid,
            },
        )

        try:
            if not self._client.is_configured():
                raise OrchestrationError(
                    "Download client is not configured - check the slskd URL in Settings"
                )
            if task.search_job_id is None or task.candidate_index is None:
                if not await self._search_score_autopick(task):
                    return  # parked for review or failed; status already set
                task = await self._store.get_task(task_id)
                if task is None:
                    return

            await self._enqueue(task)
            await self._poll_until_done(task)
            await self._process_downloaded(task)
            await self._notify_completion(task)
        except _Cancelled:
            return  # cancel_task already set status='cancelled'; don't overwrite
        except OrchestrationError as exc:
            user_msg = _user_error_message(exc)
            await self._store.update_status(task_id, "failed", error_message=user_msg)
            logger.info(
                "download.failed", extra={"task_id": task_id, "error_message": user_msg}
            )
            await self._bus.publish(
                f"download:{task_id}", "complete",
                {"status": "failed", "error": user_msg},
            )

    async def _search_score_autopick(self, task) -> bool:  # noqa: ANN001 - DownloadTask
        """Search, score, and auto-pick the top candidate.

        Returns True iff a candidate was auto-picked and linked (proceed to
        enqueue). Returns False when parked for manual review or failed (status
        already set; caller must return)."""
        timeout = 30.0 + 15.0 * min(task.retry_count, 4)

        if task.download_type == "track":
            target = TargetTrack(
                artist_name=task.artist_name,
                track_title=task.track_title or "",
                album_title=task.album_title,
                duration_seconds=task.track_duration_seconds,
            )
            results = await self._client.search_track(
                task.artist_name, task.track_title or "", task.album_title, timeout=timeout
            )
            best = self._track_matcher.match(
                target, results, auto_accept_threshold=self._auto, manual_threshold=self._manual
            )
            if asyncio.iscoroutine(best):
                best = await best
            candidates = [best] if best else []
        else:
            from models.download import TargetAlbum

            target = TargetAlbum(
                artist_name=task.artist_name,
                album_title=task.album_title,
                year=task.year,
                track_count=task.track_count,
            )
            results = await self._client.search_album(
                task.artist_name, task.album_title, task.year, task.track_count, timeout=timeout
            )
            candidates = await self._scorer.rank(
                target, results, auto_accept_threshold=self._auto, manual_threshold=self._manual
            )

        logger.info(
            "download.search.completed",
            extra={
                "task_id": task.id,
                "download_type": task.download_type,
                "results_count": len(results),
                "candidates_count": len(candidates),
                "top_score": candidates[0].final_score if candidates else 0.0,
            },
        )

        job = await self._store.create_search_job(
            user_id=task.user_id,
            artist_name=task.artist_name,
            album_title=task.album_title,
            year=task.year,
            track_count=task.track_count,
            release_group_mbid=task.release_group_mbid,
            search_query=f"{task.artist_name} - {task.album_title}",
        )
        await self._store.set_search_job_candidates(job.id, candidates)
        top = candidates[0] if candidates else None

        if top and top.final_score >= self._auto:
            await self._store.link_picked_candidate(
                task.id, job.id, 0, top.username, top.parent_directory, top.final_score
            )
            return True

        if top and top.final_score >= self._manual:
            # Park for review: search job 'completed', candidate_index NULL. The UI
            # derives 'awaiting_review'. Resumed when the user calls pick_candidate.
            await self._store.set_search_job_id_and_candidate(task.id, job.id, None)
            await self._store.update_search_job_status(job.id, "completed")
            await self._bus.publish(
                f"download:{task.id}", "status",
                {"status": "awaiting_review", "search_job_id": job.id},
            )
            return False

        await self._store.update_search_job_status(job.id, "completed")
        await self._store.update_status(
            task.id, "failed", error_message="No matching candidate found on Soulseek"
        )
        await self._bus.publish(
            f"download:{task.id}", "complete", {"status": "failed", "error": "no match"}
        )
        return False

    async def _enqueue(self, task) -> None:  # noqa: ANN001 - DownloadTask
        candidates = await self._store.get_search_job_candidates(task.search_job_id)
        if task.candidate_index is None or task.candidate_index >= len(candidates):
            raise OrchestrationError("candidate no longer available")
        candidate = candidates[task.candidate_index]

        files = [
            DownloadFileRef(username=candidate.username, filename=f.filename, size=f.size)
            for f in candidate.files
        ]
        total_size = sum(f.size for f in candidate.files)
        await self._store.update_status(
            task.id, "downloading", files_total=len(files), total_size_bytes=total_size,
            started_at=time.time(),
        )
        await self._bus.publish(
            f"download:{task.id}", "status",
            {"status": "downloading", "files_total": len(files)},
        )

        # Persist the manifest BEFORE enqueueing: it carries the correlation key
        # (source_username + the enqueued filenames) so a restart can re-correlate.
        manifest = DownloadManifest(
            task_id=task.id,
            source_username=candidate.username,
            release_group_mbid=task.release_group_mbid,
            release_mbid=task.release_mbid,
            artist_mbid=task.artist_mbid,
            artist_name=task.artist_name,
            album_title=task.album_title,
            year=task.year,
            naming_template=self._naming_template,
            target_files=[
                ExpectedFile(filename=f.filename, size=f.size, duration=f.duration)
                for f in candidate.files
            ],
        )
        self._staging.joinpath(task.id).mkdir(parents=True, exist_ok=True)
        (self._staging / task.id / "manifest.json").write_bytes(
            self._manifest_codec.encode(manifest)
        )

        try:
            await self._client.enqueue(files)
        except Exception as exc:  # noqa: BLE001 - any client error -> task failed
            # Per review-triage: do NOT quarantine on enqueue failure (nothing was
            # downloaded). The safe runner / process_task persists the sanitized msg.
            logger.exception("Enqueue failed for task %s", task.id)
            raise OrchestrationError("enqueue failed") from exc

        logger.info(
            "download.enqueued",
            extra={
                "task_id": task.id,
                "user_id": task.user_id,
                "release_group_mbid": task.release_group_mbid,
                "files_total": len(files),
                "total_size_bytes": total_size,
            },
        )

    async def _poll_until_done(self, task) -> None:  # noqa: ANN001 - DownloadTask
        manifest = self._read_manifest(task.id)
        task_ref = TaskRef(
            username=task.source_username or "",
            filenames=[f.filename for f in manifest.target_files],
        )
        deadline = asyncio.get_running_loop().time() + _POLL_DEADLINE_SECONDS
        last_logged_percent = -1
        while asyncio.get_running_loop().time() < deadline:
            # An out-of-band cancel (cancel_task) may have set status='cancelled'
            # since this loop started - stop before processing so the import can't
            # proceed against an explicit cancel.
            current = await self._store.get_task(task.id)
            if current is not None and current.status == "cancelled":
                raise _Cancelled()
            status = await self._client.get_status(task_ref)
            await self._store.update_progress(
                task.id,
                bytes_downloaded=status.bytes_downloaded,
                files_completed=status.files_completed,
                progress_percent=int(status.progress_percent),
            )
            # Throttle to one log per whole-percent change so a multi-minute
            # transfer emits ~100 lines, not one every poll interval.
            percent = int(status.progress_percent)
            if percent != last_logged_percent:
                last_logged_percent = percent
                logger.info(
                    "download.progress",
                    extra={
                        "task_id": task.id,
                        "progress_percent": percent,
                        "files_completed": status.files_completed,
                        "files_total": status.files_total,
                        "bytes_downloaded": status.bytes_downloaded,
                    },
                )
            await self._bus.publish(
                f"download:{task.id}", "progress",
                {
                    "bytes_downloaded": status.bytes_downloaded,
                    "bytes_total": status.bytes_total,
                    "files_completed": status.files_completed,
                    "files_total": status.files_total,
                    "progress_percent": status.progress_percent,
                },
            )
            if status.status in ("completed", "partial", "failed"):
                if status.status == "failed":
                    raise OrchestrationError("transfer failed")
                return
            await asyncio.sleep(self._poll_interval)
        raise OrchestrationError("timed out")

    async def _process_downloaded(self, task) -> None:  # noqa: ANN001 - DownloadTask
        await self._store.update_status(task.id, "processing")
        await self._bus.publish(f"download:{task.id}", "status", {"status": "processing"})

        manifest = self._read_manifest(task.id)
        logger.info(
            "download.processing",
            extra={"task_id": task.id, "files_total": len(manifest.target_files)},
        )
        result = await self._file_processor.process_downloaded(manifest)

        # DEC-1: the ORCHESTRATOR clears the now-completed slskd transfer records
        # (cancel == DELETE ?remove=true). Best-effort; skip when nothing imported.
        if result.succeeded:
            try:
                await self._client.cancel(
                    TaskRef(
                        username=task.source_username or "",
                        filenames=[f.filename for f in manifest.target_files],
                    )
                )
            except Exception:  # noqa: BLE001 - cleanup must not fail a good import
                logger.warning("Failed to remove slskd transfer records for task %s", task.id)

        for failure in result.failed:
            if failure.reason in QUARANTINE_REASONS:
                await self._store.record_quarantine(
                    client_id="slskd",
                    username=task.source_username or "",
                    filename=failure.filename,
                    reason=failure.reason,
                    release_group_mbid=task.release_group_mbid,
                )
                logger.info(
                    "download.quarantined",
                    extra={
                        "task_id": task.id,
                        "file": _basename(failure.filename),
                        "reason": failure.reason,
                    },
                )

        if result.succeeded:
            await self._store.set_final_path(task.id, str(Path(result.succeeded[0]).parent))

        # Staging held only the manifest; clean it whenever processing ran to
        # completion (full or partial). A hard abort leaves it for the orphan sweep.
        shutil.rmtree(self._staging / task.id, ignore_errors=True)

        now = time.time()
        if not result.succeeded:
            reasons = {f.reason for f in result.failed}
            from services.native.file_processor import DOWNLOADS_MOUNT_UNAVAILABLE

            msg = (
                DOWNLOADS_MOUNT_UNAVAILABLE
                if DOWNLOADS_MOUNT_UNAVAILABLE in reasons
                else "verification failed"
            )
            await self._store.update_status(
                task.id, "failed", error_message=msg, completed_at=now,
                files_completed=0, files_failed=len(result.failed),
            )
            logger.info(
                "download.failed",
                extra={
                    "task_id": task.id,
                    "error_message": msg,
                    "files_failed": len(result.failed),
                },
            )
        else:
            final_status = "partial" if result.failed else "completed"
            await self._store.update_status(
                task.id,
                final_status,
                completed_at=now,
                files_completed=len(result.succeeded),
                files_failed=len(result.failed),
            )
            logger.info(
                "download.completed",
                extra={
                    "task_id": task.id,
                    "status": final_status,
                    "files_completed": len(result.succeeded),
                    "files_failed": len(result.failed),
                },
            )

    async def _notify_completion(self, task) -> None:  # noqa: ANN001 - DownloadTask
        final = await self._store.get_task(task.id)
        await self._bus.publish(
            f"download:{task.id}", "complete",
            {
                "status": final.status if final else "unknown",
                "final_path": final.final_path if final else None,
            },
        )

    async def startup_resume(self) -> None:
        """Resume in-progress tasks after a restart (AUD-3): never block startup."""
        registry = TaskRegistry.get_instance()

        for orphan in await self._store.list_active_tasks(["queued"]):
            # queued = created but never enqueued -> re-dispatch (failing would be
            # spurious; they never started).
            self.dispatch(orphan.id)

        for task in await self._store.list_active_tasks(["downloading", "processing"]):
            handle = asyncio.create_task(self._resume_single_task(task.id))
            # Track the live handle so cancel_task can stop the resumed poll loop
            # (mirrors dispatch); without this a resumed download is uncancellable.
            self._active_tasks[task.id] = handle
            handle.add_done_callback(_log_task_exception)
            handle.add_done_callback(lambda _t, _id=task.id: self._active_tasks.pop(_id, None))
            registry.register(f"download-resume-{task.id}", handle)

    async def _resume_single_task(self, task_id: str) -> None:
        task = await self._store.get_task(task_id)
        if task is None:
            return
        try:
            manifest = self._read_manifest(task_id)
            status = await self._client.get_status(
                TaskRef(
                    username=task.source_username or "",
                    filenames=[f.filename for f in manifest.target_files],
                )
            )
            if status.status in ("completed", "partial"):
                await self._process_downloaded(task)
                await self._notify_completion(task)
            elif status.status == "downloading":
                await self._poll_until_done(task)
                await self._process_downloaded(task)
                await self._notify_completion(task)
            else:
                await self._store.update_status(
                    task_id, "failed", error_message="Transfer lost during restart"
                )
        except _Cancelled:
            return  # cancelled mid-resume; status already 'cancelled'
        except Exception as exc:  # noqa: BLE001 - resume failure -> mark failed
            logger.exception("Failed to resume task %s", task_id)
            await self._store.update_status(
                task_id, "failed", error_message=_user_error_message(exc)
            )

    async def cancel_task(self, task_id: str, user_id: str, user_role: str) -> None:
        task = await self._store.get_task(task_id)
        if task is None:
            raise ResourceNotFoundError("Download task not found")
        if user_role != "admin" and task.user_id != user_id:
            raise PermissionDeniedError("Cannot cancel another user's download")

        manifest_path = self._staging / task_id / "manifest.json"
        if task.source_username and manifest_path.exists():
            try:
                manifest = self._manifest_codec.decode(manifest_path.read_bytes())
                await self._client.cancel(
                    TaskRef(
                        username=task.source_username,
                        filenames=[f.filename for f in manifest.target_files],
                    )
                )
            except Exception as exc:  # noqa: BLE001 - best-effort
                logger.warning("Failed to cancel slskd transfers for %s: %s", task_id, exc)

        # Stop the live poll loop promptly if one is running in this process.
        handle = self._active_tasks.pop(task_id, None)
        if handle is not None and not handle.done():
            handle.cancel()

        await self._store.update_status(task_id, "cancelled", cancelled_at=time.time())
        logger.info(
            "download.cancelled", extra={"task_id": task_id, "user_id": task.user_id}
        )
        await self._bus.publish(
            f"download:{task_id}", "complete", {"status": "cancelled"}
        )

    async def retry_task(self, task_id: str, user_id: str, user_role: str) -> str:
        task = await self._store.get_task(task_id)
        if task is None:
            raise ResourceNotFoundError("Download task not found")
        if user_role != "admin" and task.user_id != user_id:
            raise PermissionDeniedError("Cannot retry another user's download")
        if task.status not in ("failed", "cancelled", "partial"):
            raise ValidationError("Only failed, cancelled or partial downloads can be retried")

        # Clean slate (Q3-A): a new task, carrying retry_count + 1 so the search
        # timeout escalates. The original is kept (terminal) for audit.
        new_task = await self._store.create_task(
            user_id=task.user_id,
            download_type=task.download_type,
            release_group_mbid=task.release_group_mbid,
            release_mbid=task.release_mbid,
            recording_mbid=task.recording_mbid,
            artist_mbid=task.artist_mbid,
            artist_name=task.artist_name,
            album_title=task.album_title,
            track_title=task.track_title,
            year=task.year,
            track_count=task.track_count,
            search_query=task.search_query,
            retry_count=task.retry_count + 1,
        )
        self.dispatch(new_task.id)
        return new_task.id

    def _read_manifest(self, task_id: str) -> DownloadManifest:
        path = self._staging / task_id / "manifest.json"
        if not path.exists():
            raise OrchestrationError("manifest missing")
        return self._manifest_codec.decode(path.read_bytes())
