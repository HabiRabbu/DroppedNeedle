"""FreeMusicService - DroppedNeedle's own lawful download client (D24).

Requests are served from the Internet Archive, restricted to items carrying an
explicit Creative Commons or public-domain licence. Downloaded files are handed
to the drop-import pipeline (01c), which identifies them against MusicBrainz,
tags, organises, resolves the request, and notifies the requester.

Why this exists: DroppedNeedle's download capability is lawful *because* it has
a demonstrated lawful use. Free Music is that use. A broken Free Music client is
a P1, not a curiosity. See .dev-notes/Plans/FreeMusic/00-PLAN.md.
"""

import asyncio
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from core.exceptions import ResourceNotFoundError, ValidationError
from models.free_music import FreeMusicCandidate, FreeMusicStatus, FreeMusicTask
from services.native.quality_tiers import tier_for, tier_rank
from services.native.title_match import title_containment_score

if TYPE_CHECKING:
    from infrastructure.persistence.free_music_store import FreeMusicStore
    from infrastructure.sse_publisher import SSEPublisher
    from repositories.archive_repository import ArchiveRepository
    from services.native.drop_import_service import DropImportService
    from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)

# A candidate whose title bears no resemblance to the requested album is a
# different record that merely shares an artist. The Archive is full of remasters,
# tributes, and live sets - none of them the album that was asked for.
_TITLE_MATCH_FLOOR = 0.60

# Write progress to SQLite at most this often; the download loop updates far faster.
_PROGRESS_WRITE_INTERVAL = 1.0
_CHUNK = 1024 * 256


class FreeMusicService:
    def __init__(
        self,
        *,
        store: "FreeMusicStore",
        archive: "ArchiveRepository",
        drop_import: "DropImportService",
        preferences_service: "PreferencesService",
        sse_publisher: "SSEPublisher",
    ) -> None:
        self._store = store
        self._archive = archive
        self._drop_import = drop_import
        self._prefs = preferences_service
        self._sse = sse_publisher
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancels: dict[str, asyncio.Event] = {}
        self._lifecycle_locks: dict[str, asyncio.Lock] = {}

    # -- public API (mirrors DownloadService's dispatch surface) --

    def is_ready(self) -> bool:
        return self._prefs.get_free_music_settings().enabled

    async def request_album(
        self,
        *,
        user_id: str,
        release_group_mbid: str,
        artist_name: str,
        album_title: str,
        track_count: int = 0,
    ) -> str:
        return await self._start(
            user_id=user_id,
            kind="album",
            mbid=release_group_mbid,
            artist=artist_name,
            title=album_title,
            track_count=track_count,
        )

    async def request_track(
        self,
        *,
        user_id: str,
        recording_mbid: str,
        artist_name: str,
        track_title: str,
    ) -> str:
        return await self._start(
            user_id=user_id,
            kind="track",
            mbid=recording_mbid,
            artist=artist_name,
            title=track_title,
        )

    async def list_tasks(
        self, *, user_id: str, include_all: bool
    ) -> list[FreeMusicTask]:
        return await self._store.list_tasks(user_id=None if include_all else user_id)

    async def get_task(
        self, task_id: str, *, user_id: str, is_admin: bool
    ) -> FreeMusicTask:
        task = await self._store.get(task_id)
        if task is None or (task.user_id != user_id and not is_admin):
            raise ResourceNotFoundError("Download not found")
        return task

    async def cancel(
        self, task_id: str, *, user_id: str, is_admin: bool
    ) -> FreeMusicTask:
        task = await self.get_task(task_id, user_id=user_id, is_admin=is_admin)
        if task.status in FreeMusicStatus.TERMINAL:
            raise ValidationError("That download has already finished")
        lock = self._lifecycle_locks.get(task_id)
        if lock is None:
            raise ValidationError("That download is no longer running")
        async with lock:
            current = await self._store.get(task_id)
            if current is None:
                raise ResourceNotFoundError("Download not found")
            if current.status == FreeMusicStatus.IMPORTING:
                raise ValidationError(
                    "This download is already being added to your library"
                )
            event = self._cancels.get(task_id)
            if event is not None:
                event.set()
            cancelled = await self._store.cancel_active(task_id)
        if cancelled is None:
            raise ValidationError("That download has already finished")
        await self._publish(cancelled.user_id, task_id, FreeMusicStatus.CANCELLED)
        return cancelled

    async def retry(
        self, task_id: str, *, user_id: str, is_admin: bool
    ) -> FreeMusicTask:
        task = await self.get_task(task_id, user_id=user_id, is_admin=is_admin)
        if task.status not in (FreeMusicStatus.FAILED, FreeMusicStatus.CANCELLED):
            raise ValidationError("Only a failed or cancelled download can be retried")
        running = self._tasks.get(task_id)
        if running is not None and not running.done():
            raise ValidationError("Wait for this download to stop before retrying")
        if not await self._store.restart_terminal(task_id):
            raise ValidationError("That download is no longer available to retry")
        self._spawn(task_id, task)
        refreshed = await self._store.get(task_id)
        assert refreshed is not None
        return refreshed

    async def remove(self, task_id: str, *, user_id: str, is_admin: bool) -> None:
        task = await self.get_task(task_id, user_id=user_id, is_admin=is_admin)
        if task.status not in FreeMusicStatus.TERMINAL:
            raise ValidationError("Cancel this download before removing it")
        removed = await self._store.delete_terminal(task_id)
        if removed is None:
            raise ValidationError("That download is no longer available to remove")
        await self._publish(removed.user_id, task_id, "removed")

    async def clear_history(self, *, user_id: str, include_all: bool) -> int:
        removed = await self._store.delete_terminal_tasks(
            user_id=None if include_all else user_id
        )
        for owner_id in {owner_id for _task_id, owner_id in removed}:
            await self._publish(owner_id, "", "removed")
        return len(removed)

    async def sweep_stale(self) -> None:
        failed = await self._store.fail_stale(
            "Interrupted by a restart. Request it again."
        )
        if failed:
            logger.info("free_music.stale_failed", extra={"tasks": failed})

    # -- task lifecycle --

    async def _start(
        self,
        *,
        user_id: str,
        kind: str,
        mbid: str,
        artist: str,
        title: str,
        track_count: int = 0,
    ) -> str:
        if not self.is_ready():
            raise ValidationError("Free Music is not enabled")
        task_id = uuid.uuid4().hex
        task = FreeMusicTask(
            id=task_id,
            user_id=user_id,
            kind=kind,
            mbid=mbid,
            artist=artist,
            title=title,
            status=FreeMusicStatus.SEARCHING,
            created_at=time.time(),
            updated_at=time.time(),
        )
        # the row exists before we return: the caller links the request to this id
        await self._store.create(task_id, user_id, kind, mbid, artist, title)
        self._spawn(task_id, task, track_count)
        return task_id

    def _spawn(self, task_id: str, task: FreeMusicTask, track_count: int = 0) -> None:
        cancel = asyncio.Event()
        lifecycle_lock = asyncio.Lock()
        self._cancels[task_id] = cancel
        self._lifecycle_locks[task_id] = lifecycle_lock
        handle = asyncio.create_task(
            self._run_guarded(task_id, task, track_count, cancel, lifecycle_lock)
        )
        self._tasks[task_id] = handle
        handle.add_done_callback(lambda t, tid=task_id: self._on_done(tid, t))

    def _on_done(self, task_id: str, handle: asyncio.Task) -> None:
        if self._tasks.get(task_id) is handle:
            self._tasks.pop(task_id, None)
            self._cancels.pop(task_id, None)
            self._lifecycle_locks.pop(task_id, None)
        if not handle.cancelled() and handle.exception() is not None:
            logger.error(
                "free_music task %s crashed", task_id, exc_info=handle.exception()
            )

    async def _run_guarded(
        self,
        task_id: str,
        task: FreeMusicTask,
        track_count: int,
        cancel: asyncio.Event,
        lifecycle_lock: asyncio.Lock,
    ) -> None:
        try:
            await self._run(task_id, task, track_count, cancel, lifecycle_lock)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Free Music task %s failed", task_id)
            await self._fail(task_id, task.user_id, "Something went wrong. Try again.")

    async def _run(
        self,
        task_id: str,
        task: FreeMusicTask,
        track_count: int,
        cancel: asyncio.Event,
        lifecycle_lock: asyncio.Lock,
    ) -> None:
        try:
            candidates = await self._find_candidates(task, track_count)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.warning("free_music.search_failed mbid=%s: %s", task.mbid, exc)
            await self._fail(
                task_id, task.user_id, "Couldn't reach the Internet Archive."
            )
            return

        if not candidates:
            await self._fail(
                task_id, task.user_id, "No source has this - try buying it instead."
            )
            return
        if cancel.is_set():
            return

        best = candidates[0]
        downloading = await self._store.update(
            task_id,
            status=FreeMusicStatus.DOWNLOADING,
            identifier=best.identifier,
            licence_url=best.licence_url,
            format=best.extension,
            files_total=len(best.filenames),
            bytes_total=best.size_bytes,
            expected_statuses=(FreeMusicStatus.SEARCHING,),
        )
        if not downloading:
            return
        await self._publish(task.user_id, task_id, FreeMusicStatus.DOWNLOADING)

        dest = self._drop_import.incoming_dir() / f"free-{task_id}"
        try:
            files = await self._download_with_retry(task_id, task, best, dest, cancel)
        except _Cancelled:
            await asyncio.to_thread(shutil.rmtree, dest, True)
            return
        except Exception as exc:  # noqa: BLE001 - the user is waiting; report it
            logger.warning("free_music.download_failed task=%s: %s", task_id, exc)
            await asyncio.to_thread(shutil.rmtree, dest, True)
            await self._fail(task_id, task.user_id, "The download failed. Try again.")
            return

        if not files:
            await asyncio.to_thread(shutil.rmtree, dest, True)
            await self._fail(task_id, task.user_id, "The download produced no files.")
            return

        async with lifecycle_lock:
            if cancel.is_set():
                await asyncio.to_thread(shutil.rmtree, dest, True)
                return
            importing = await self._store.update(
                task_id,
                status=FreeMusicStatus.IMPORTING,
                expected_statuses=(FreeMusicStatus.DOWNLOADING,),
            )
        if not importing:
            await asyncio.to_thread(shutil.rmtree, dest, True)
            return
        await self._publish(task.user_id, task_id, FreeMusicStatus.IMPORTING)
        try:
            # the drop importer identifies, tags, organises, resolves the request,
            # and notifies the requester - the same path a dropped Bandcamp zip takes
            await self._drop_import.create_job(
                user_id=task.user_id,
                user_name="Free Music",
                uploads=[(f.name, f) for f in files],
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, dest, True)

        completed = await self._store.update(
            task_id,
            status=FreeMusicStatus.COMPLETED,
            expected_statuses=(FreeMusicStatus.IMPORTING,),
        )
        if not completed:
            return
        await self._publish(task.user_id, task_id, FreeMusicStatus.COMPLETED)
        logger.info(
            "free_music.completed",
            extra={
                "task_id": task_id,
                "identifier": best.identifier,
                "files": len(files),
            },
        )

    # -- candidates --

    async def _find_candidates(
        self, task: FreeMusicTask, track_count: int
    ) -> list[FreeMusicCandidate]:
        items = await self._archive.search_audio(task.artist, task.title)
        preferred = self._prefs.get_free_music_settings().preferred_format.lower()

        candidates: list[FreeMusicCandidate] = []
        for item in items:
            if title_containment_score(task.title, item.title) < _TITLE_MATCH_FLOOR:
                continue
            licence, files = await self._archive.get_item_files(item.identifier)
            if not licence or not files:
                continue  # dark item, or one whose licence we cannot read

            by_format: dict[str, list] = {}
            for entry in files:
                by_format.setdefault(entry.format, []).append(entry)

            for fmt, entries in by_format.items():
                extension = self._archive.extension_for(fmt)
                if not extension:
                    continue
                chosen = self._select_files(task, entries)
                if not chosen:
                    continue
                candidates.append(
                    FreeMusicCandidate(
                        identifier=item.identifier,
                        title=item.title,
                        creator=item.creator,
                        licence_url=licence,
                        format=fmt,
                        extension=extension,
                        track_count=len(chosen),
                        size_bytes=sum(e.size_bytes for e in chosen),
                        filenames=[e.name for e in chosen],
                    )
                )

        candidates.sort(key=lambda c: self._rank(c, preferred, track_count))
        return candidates

    def _select_files(self, task: FreeMusicTask, entries: list) -> list:
        """An album takes every file of its format; a track takes the one whose
        title matches."""
        if task.kind == "album":
            return sorted(entries, key=lambda e: (e.track or 0, e.name))
        best = None
        best_score = 0.0
        for entry in entries:
            score = title_containment_score(task.title, entry.title or entry.name)
            if score > best_score:
                best, best_score = entry, score
        return [best] if best is not None and best_score >= _TITLE_MATCH_FLOOR else []

    @staticmethod
    def _rank(candidate: FreeMusicCandidate, preferred: str, track_count: int) -> tuple:
        """Lower sorts first.

        Agreement with MusicBrainz's track count comes FIRST: getting the right
        record matters more than getting it in the right format, and the Archive
        is full of two-track samplers of ten-track albums. Only then the admin's
        preferred format, the quality tier, and finally the larger (better-encoded)
        copy. With no MusicBrainz track count the first key is flat and format
        preference decides.
        """
        count_delta = abs(candidate.track_count - track_count) if track_count else 0
        not_preferred = 0 if candidate.extension == preferred else 1
        quality = -tier_rank(tier_for(candidate.extension, None))
        return (count_delta, not_preferred, quality, -candidate.size_bytes)

    # -- download --

    async def _download_with_retry(
        self,
        task_id: str,
        task: FreeMusicTask,
        candidate: FreeMusicCandidate,
        dest: Path,
        cancel: asyncio.Event,
    ) -> list[Path]:
        """One retry on a transient failure, then give up. The Archive does not
        lie about its files, so there is nothing to fail over to."""
        last: Exception | None = None
        for attempt in (1, 2):
            updated = await self._store.update(
                task_id,
                attempts=attempt,
                expected_statuses=(FreeMusicStatus.DOWNLOADING,),
            )
            if not updated:
                raise _Cancelled
            try:
                return await self._download(task_id, task, candidate, dest, cancel)
            except _Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - retried once, then surfaced
                last = exc
                logger.info(
                    "free_music.download_attempt_failed task=%s attempt=%s: %s",
                    task_id,
                    attempt,
                    exc,
                )
                await asyncio.to_thread(shutil.rmtree, dest, True)
                if cancel.is_set():
                    raise _Cancelled from exc
        raise last if last else RuntimeError("download failed")

    async def _download(
        self,
        task_id: str,
        task: FreeMusicTask,
        candidate: FreeMusicCandidate,
        dest: Path,
        cancel: asyncio.Event,
    ) -> list[Path]:
        await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)
        written: list[Path] = []
        downloaded = 0
        last_write = 0.0

        for index, name in enumerate(candidate.filenames):
            if cancel.is_set():
                raise _Cancelled
            target = dest / Path(name).name
            with open(target, "wb") as out:
                async for chunk in self._archive.stream_file(
                    candidate.identifier, name
                ):
                    if cancel.is_set():
                        raise _Cancelled
                    out.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_write >= _PROGRESS_WRITE_INTERVAL:
                        last_write = now
                        updated = await self._store.update(
                            task_id,
                            bytes_downloaded=downloaded,
                            files_completed=index,
                            expected_statuses=(FreeMusicStatus.DOWNLOADING,),
                        )
                        if not updated:
                            raise _Cancelled
                        await self._publish(
                            task.user_id, task_id, FreeMusicStatus.DOWNLOADING
                        )
            written.append(target)

        updated = await self._store.update(
            task_id,
            bytes_downloaded=downloaded,
            files_completed=len(written),
            expected_statuses=(FreeMusicStatus.DOWNLOADING,),
        )
        if not updated:
            raise _Cancelled
        return written

    # -- helpers --

    async def _fail(self, task_id: str, user_id: str, message: str) -> None:
        failed = await self._store.update(
            task_id,
            status=FreeMusicStatus.FAILED,
            error=message,
            expected_statuses=(
                FreeMusicStatus.SEARCHING,
                FreeMusicStatus.DOWNLOADING,
                FreeMusicStatus.IMPORTING,
            ),
        )
        if not failed:
            return
        await self._publish(user_id, task_id, FreeMusicStatus.FAILED)

    async def _publish(self, user_id: str, task_id: str, status: str) -> None:
        # status rides along so the client can sweep its library caches on a
        # completion without doing it on every once-a-second progress tick
        try:
            await self._sse.publish(
                f"user:{user_id}",
                "free_music_updated",
                {
                    "event_id": uuid.uuid4().hex,
                    "task_id": task_id,
                    "status": status,
                },
            )
        except Exception as exc:  # noqa: BLE001 - progress push is best-effort
            logger.debug("free_music_updated publish failed: %s", exc)


class _Cancelled(Exception):
    """Internal: the user cancelled mid-download."""
