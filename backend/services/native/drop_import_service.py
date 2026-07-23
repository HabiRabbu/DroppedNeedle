"""DropImportService - the Store Sync drop importer (phase 01c).

The user buys music anywhere, downloads the archive from the store's own site,
and hands it to DN. This service stages the upload, safely extracts archives,
identifies each album-shaped unit with the same tiered logic the scanner uses
(MBID tags, then a tag-based album match, then an AcoustID-backed match),
organises identified files into the library via the naming template, and
resolves any open request for the album. Units nothing could identify become
``needs_review`` items the user matches manually (against a release group they
pick) or discards.

Boundaries:
- Only the user's own files ever enter here (an upload); nothing is fetched.
- Identified files are submitted as one durable staged bundle. The shared publisher
  stamps the minimal album identity, publishes atomically per file, and commits the
  complete catalog unit with ``source='drop'``.
- Duplicate policy (owner-signed): a file whose album position is already
  covered imports only when strictly better quality (the old file goes to the
  recycle bin, download-upgrade semantics); otherwise it is skipped.
"""

import asyncio
import hashlib
import logging
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, NamedTuple

import msgspec

from core.exceptions import (
    AutomaticManagementHoldError,
    ResourceNotFoundError,
    ValidationError,
)
from models.drop_import import DropImportItem, DropImportJob, ItemStatus, JobStatus
from models.library_management import (
    LibraryManagementImportBundle,
    LibraryManagementImportFile,
    LibraryManagementImportResult,
)
from services.native.album_matcher import LocalTrack, MBTrack, score_release
from services.native.file_processor import row_covers_track
from services.native.library_manager import _AUDIO_SUFFIXES
from services.native.naming import NamingTemplateEngine
from services.native.quality_tiers import tier_for, tier_rank
from services.native.recycle_bin import resolve_bin_path

if TYPE_CHECKING:
    from infrastructure.audio.fingerprinter import AudioFingerprinter
    from infrastructure.audio.tagger import AudioTagger
    from infrastructure.persistence.drop_import_store import DropImportStore
    from infrastructure.persistence.request_history import RequestHistoryStore
    from infrastructure.persistence.wanted_store import WantedStore
    from infrastructure.sse_publisher import SSEPublisher
    from models.audio import AudioInfo, AudioTag, FingerprintResult
    from services.native.album_matcher import AlbumIdentifier, AlbumMatch
    from services.native.library_manager import LibraryManager
    from services.native.musicbrainz_matcher import MusicBrainzMatcher
    from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)

# mirror the scanner's thresholds so a drop identifies exactly like a scan would
_FINGERPRINT_SCORE_THRESHOLD = 0.70
_UNMAPPED_CONFIDENCE = 0.5
_MAX_FILES_PER_UNIT = 60

# archive safety rails: far above any real purchase, far below a zip bomb
_MAX_ARCHIVE_ENTRIES = 4096
_MAX_ARCHIVE_TOTAL_BYTES = 64 * 2**30

_SOURCE = "drop"
_LOOSE_UNIT_NAME = "Loose tracks"

# Callback the DI layer wires to the canonical import invalidation (cache bust +
# album-row materialisation) so a dropped album surfaces in the UI immediately.
OnImport = Callable[..., Awaitable[None]]


class _Entry(NamedTuple):
    path: Path
    tag: "AudioTag"
    info: "AudioInfo"


class _Identified(NamedTuple):
    meta: object  # album_matcher._ReleaseMeta
    tracks: "list[MBTrack]"
    match: "AlbumMatch"


class _OrganiseResult(NamedTuple):
    imported: int
    upgraded: int
    skipped: int
    bonus: int


class _PlannedDropImport(NamedTuple):
    entry: _Entry
    target: Path
    tag: "AudioTag"
    recording_mbid: str | None
    release_track_mbid: str | None
    medium_position: int | None
    release_track_position: int | None
    authoritative_mapping: bool
    confidence: float
    replacement: dict | None
    bonus: bool


def _strip_stage_prefix(stem: str) -> str:
    """Drop the NNN_ collision prefix create_job adds to staged uploads."""
    return re.sub(r"^\d{3}_", "", stem) or stem


def _safe_component(name: str) -> str:
    """A filesystem-safe single path component for staging (never for the
    library - the naming engine owns that)."""
    cleaned = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", name).strip(" .")
    return cleaned or "upload"


class DropImportService:
    def __init__(
        self,
        *,
        store: "DropImportStore",
        tagger: "AudioTagger",
        fingerprinter: "AudioFingerprinter",
        album_identifier: "AlbumIdentifier",
        mb_matcher: "MusicBrainzMatcher",
        naming_engine: "NamingTemplateEngine",
        library_manager: "LibraryManager",
        preferences_service: "PreferencesService",
        request_history: "RequestHistoryStore",
        wanted_store: "WantedStore",
        sse_publisher: "SSEPublisher",
        on_import: OnImport,
        staging_root: Path,
        publish_import_bundle: (
            Callable[
                [LibraryManagementImportBundle],
                Awaitable[LibraryManagementImportResult],
            ]
            | None
        ) = None,
        policy_revision_getter: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._tagger = tagger
        self._fingerprinter = fingerprinter
        self._identifier = album_identifier
        self._mb_matcher = mb_matcher
        self._naming = naming_engine
        self._library = library_manager
        self._prefs = preferences_service
        self._requests = request_history
        self._wanted = wanted_store
        self._sse = sse_publisher
        self._on_import = on_import
        self._staging_root = staging_root
        self._publish_import_bundle = publish_import_bundle
        self._policy_revision_getter = policy_revision_getter
        self._tasks: dict[str, asyncio.Task] = {}

    # -- public API --

    def incoming_dir(self) -> Path:
        """Where the route streams uploads before a job exists. Same filesystem
        as the job staging dirs, so adopting them into a job is a rename."""
        path = self._staging_root / "_incoming"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def create_job(
        self, *, user_id: str, user_name: str, uploads: list[tuple[str, Path]]
    ) -> DropImportJob:
        """Register an upload as a job and start processing it in the background.
        ``uploads`` are (original filename, temp path) pairs the route already
        wrote to disk; this moves them into the job's staging directory."""
        if not uploads:
            raise ValidationError("No files were uploaded")
        self._require_library_root()

        job_id = uuid.uuid4().hex
        staging_dir = self._staging_root / job_id

        def _stage() -> None:
            staging_dir.mkdir(parents=True, exist_ok=True)
            for index, (name, tmp_path) in enumerate(uploads):
                target = staging_dir / f"{index:03d}_{_safe_component(name)}"
                shutil.move(str(tmp_path), str(target))

        await asyncio.to_thread(_stage)

        first_name = uploads[0][0]
        upload_name = (
            first_name
            if len(uploads) == 1
            else f"{first_name} +{len(uploads) - 1} more"
        )
        await self._store.create_job(
            job_id, user_id, user_name, upload_name, str(staging_dir)
        )
        task = asyncio.create_task(self._run_job(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda t, jid=job_id: self._on_task_done(jid, t))
        job = await self._store.get_job(job_id)
        assert job is not None  # just created
        return job

    async def list_jobs(
        self, *, user_id: str, include_all: bool
    ) -> list[DropImportJob]:
        return await self._store.list_jobs(user_id=None if include_all else user_id)

    async def get_job(
        self, job_id: str, *, user_id: str, is_admin: bool
    ) -> DropImportJob:
        job = await self._store.get_job(job_id)
        if job is None or (job.user_id != user_id and not is_admin):
            raise ResourceNotFoundError("Import job not found")
        return job

    async def match_item(
        self, item_id: int, release_group_mbid: str, *, user_id: str, is_admin: bool
    ) -> DropImportItem:
        """Force-import a ``needs_review`` item against a user-chosen release
        group. Track assignment is best-effort (``score_release`` without the
        acceptance gate) - the user's choice of album is authoritative."""
        item, job = await self._owned_item(item_id, user_id, is_admin)
        if item.status != ItemStatus.NEEDS_REVIEW:
            raise ValidationError("Only items awaiting review can be matched")
        rg = (release_group_mbid or "").strip()
        if not rg:
            raise ValidationError("A release group is required")

        entries, unreadable = await self._read_entries(
            [Path(p) for p in item.staging_paths if Path(p).exists()]
        )
        if not entries:
            raise ValidationError("The staged files no longer exist on disk")

        picked = await self._identifier.release_tracks(rg, len(entries))
        if picked is None:
            raise ValidationError("Could not load that release group from MusicBrainz")
        meta, tracks = picked
        match = score_release([self._to_local(e) for e in entries], tracks, meta)
        ident = _Identified(meta=meta, tracks=tracks, match=match)

        # the user's explicit choice is authoritative: full confidence, so the
        # scanner's sticky-anchor guard protects it from later re-attribution
        try:
            result = await self._organise(
                entries,
                ident,
                confidence_override=1.0,
                idempotency_key=f"drop:{job.id}:{item.id}:manual",
            )
        except AutomaticManagementHoldError as hold:
            await self._store.update_item(
                item.id,
                status=ItemStatus.NEEDS_REVIEW,
                detail=(
                    f"Library Management still holds this album ({hold.reason_code}). "
                    "Fix the profile or provider, then retry."
                ),
            )
            refreshed = await self._store.get_item(item.id)
            assert refreshed is not None
            return refreshed
        await self._finish_item(job, item.id, ident, result, unreadable, staged=entries)
        await self._publish_job(job)
        refreshed = await self._store.get_item(item.id)
        assert refreshed is not None
        return refreshed

    async def discard_item(
        self, item_id: int, *, user_id: str, is_admin: bool
    ) -> DropImportItem:
        item, job = await self._owned_item(item_id, user_id, is_admin)
        if item.status != ItemStatus.NEEDS_REVIEW:
            raise ValidationError("Only items awaiting review can be discarded")

        def _remove() -> None:
            for raw in item.staging_paths:
                try:
                    Path(raw).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove staged file %s", raw)

        await asyncio.to_thread(_remove)
        await self._store.update_item(
            item.id, status=ItemStatus.DISCARDED, staging_paths=[], detail="Discarded"
        )
        await self._publish_job(job)
        refreshed = await self._store.get_item(item.id)
        assert refreshed is not None
        return refreshed

    async def sweep_stale(self) -> None:
        """Startup housekeeping: jobs whose task died with the process are
        failed, and staging directories with nothing left to review are removed."""
        detail = "The server restarted mid-import. Drop the files in again."
        failed = await self._store.fail_stale_processing(detail)
        if failed:
            logger.info("drop_import.stale_failed", extra={"jobs": failed})
        jobs = await self._store.list_jobs(limit=500)

        def _cleanup(dirs: list[str]) -> None:
            for raw in dirs:
                shutil.rmtree(raw, ignore_errors=True)

        removable = [
            job.staging_dir
            for job in jobs
            if job.status != JobStatus.PROCESSING
            and not any(i.status == ItemStatus.NEEDS_REVIEW for i in job.items)
            and Path(job.staging_dir).exists()
        ]
        if removable:
            await asyncio.to_thread(_cleanup, removable)

    # -- job processing --

    def _on_task_done(self, job_id: str, task: asyncio.Task) -> None:
        self._tasks.pop(job_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Drop import job %s crashed", job_id, exc_info=exc)

    async def _run_job(self, job_id: str) -> None:
        try:
            await self._process_job(job_id)
        except Exception:
            logger.exception("Drop import job %s failed", job_id)
            try:
                await self._store.set_job_status(
                    job_id,
                    JobStatus.FAILED,
                    "The import didn't finish. Check the server logs.",
                )
                job = await self._store.get_job(job_id)
                if job:
                    await self._publish_job(job)
            except Exception:  # noqa: BLE001 - the failure path must not raise again
                logger.warning("Could not record failure for drop job %s", job_id)

    async def _process_job(self, job_id: str) -> None:
        job = await self._store.get_job(job_id)
        if job is None:
            return
        units, notes = await asyncio.to_thread(
            self._extract_and_group, Path(job.staging_dir)
        )
        if notes:
            logger.info(
                "drop_import.extract_notes", extra={"job_id": job_id, "notes": notes}
            )
        if not units:
            error = notes[0] if notes else "No audio files found in the upload"
            await self._store.set_job_status(job_id, JobStatus.FAILED, error)
            await self._publish_job(job)
            return

        item_ids: list[tuple[int, str, list[Path]]] = []
        for folder_name, paths in units:
            item_id = await self._store.add_item(
                job_id, folder_name, [str(p) for p in paths], len(paths)
            )
            item_ids.append((item_id, folder_name, paths))
        await self._publish_job(job)

        for item_id, _folder_name, paths in item_ids:
            try:
                await self._process_item(job, item_id, paths)
            except Exception:
                logger.exception("Drop import item %s failed", item_id)
                await self._store.update_item(
                    item_id,
                    status=ItemStatus.FAILED,
                    detail="Couldn't import this folder.",
                )
            await self._publish_job(job)

        # a corrupt/oversized archive alongside good ones must still be reported:
        # the job completes, and the notes ride along so the user sees what was
        # skipped rather than silently getting fewer albums than they dropped
        await self._store.set_job_status(
            job_id, JobStatus.COMPLETED, "; ".join(notes) if notes else None
        )
        await asyncio.to_thread(self._remove_empty_dirs, Path(job.staging_dir))
        await self._publish_job(job)

    def _extract_and_group(
        self, staging_dir: Path
    ) -> tuple[list[tuple[str, list[Path]]], list[str]]:
        """Extract every archive in the staging dir, then group all audio into
        album-shaped units: one per top-level folder, plus one for loose files.
        Runs in a worker thread (archive extraction is heavy blocking work)."""
        notes: list[str] = []
        for child in sorted(staging_dir.iterdir()):
            if not child.is_file() or child.suffix.lower() != ".zip":
                continue
            # staged uploads carry an NNN_ collision prefix; strip it so item
            # names and messages read as the user's own filename, falling back
            # to the prefixed stem when two zips share a name
            display = _strip_stage_prefix(child.stem)
            target = staging_dir / _safe_component(display)
            if target.exists():
                target = staging_dir / _safe_component(child.stem)
            # a truncated upload can carry a zip header and still fail to open;
            # say so rather than letting the file vanish unremarked
            if not zipfile.is_zipfile(child):
                notes.append(f"Couldn't read {display}.zip - the archive is corrupt.")
            else:
                try:
                    self._safe_extract(child, target, notes, display=f"{display}.zip")
                except zipfile.BadZipFile:
                    notes.append(
                        f"Couldn't read {display}.zip - the archive is corrupt."
                    )
            child.unlink(missing_ok=True)

        units: dict[str, list[Path]] = {}
        for child in sorted(staging_dir.iterdir()):
            if child.is_dir():
                audio = sorted(
                    p
                    for p in child.rglob("*")
                    if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES
                )
                if audio:
                    units[child.name] = audio
            elif child.is_file() and child.suffix.lower() in _AUDIO_SUFFIXES:
                units.setdefault(_LOOSE_UNIT_NAME, []).append(child)
        return list(units.items()), notes

    def _safe_extract(
        self, archive: Path, target_dir: Path, notes: list[str], *, display: str = ""
    ) -> None:
        """Extract only audio entries, refusing traversal, absolute paths, and
        decompression bombs. The size cap counts bytes actually written, not the
        zip's declared sizes - headers can lie. Non-audio entries are counted,
        not extracted."""
        skipped = 0
        written_total = 0
        label = display or archive.name
        with zipfile.ZipFile(archive) as zf:
            entries = zf.infolist()
            if len(entries) > _MAX_ARCHIVE_ENTRIES:
                notes.append(f"Skipped {label} - too many files.")
                return
            if sum(e.file_size for e in entries) > _MAX_ARCHIVE_TOTAL_BYTES:
                notes.append(f"Skipped {label} - archive too large.")
                return
            for entry in entries:
                if entry.is_dir():
                    continue
                raw = Path(entry.filename)
                if raw.is_absolute() or ".." in raw.parts:
                    skipped += 1
                    continue
                if raw.suffix.lower() not in _AUDIO_SUFFIXES:
                    skipped += 1
                    continue
                safe = target_dir.joinpath(*(_safe_component(p) for p in raw.parts))
                safe.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(entry) as src, open(safe, "wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        written_total += len(chunk)
                        if written_total > _MAX_ARCHIVE_TOTAL_BYTES:
                            dst.close()
                            safe.unlink(missing_ok=True)
                            notes.append(
                                f"Stopped extracting {label} - it unpacks "
                                "far larger than it claims."
                            )
                            return
                        dst.write(chunk)
        if skipped:
            notes.append(
                f"{label}: ignored {skipped} non-audio "
                f"{'file' if skipped == 1 else 'files'}."
            )

    @staticmethod
    def _remove_empty_dirs(root: Path) -> None:
        if not root.exists():
            return
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass  # not empty - a needs_review unit still lives here
        try:
            root.rmdir()
        except OSError:
            pass

    async def _process_item(
        self, job: DropImportJob, item_id: int, paths: list[Path]
    ) -> None:
        entries, unreadable = await self._read_entries(paths)
        if not entries:
            await self._store.update_item(
                item_id,
                status=ItemStatus.FAILED,
                detail="No readable audio files",
                staging_paths=[],
            )
            return
        if len(entries) > _MAX_FILES_PER_UNIT:
            await self._store.update_item(
                item_id,
                status=ItemStatus.NEEDS_REVIEW,
                detail=(
                    f"Too many files to be one album ({len(entries)}). "
                    "Match it manually, or discard it."
                ),
            )
            return

        ident = await self._identify(entries)
        if ident is None:
            detail = "Couldn't work out which album this is. Match it manually."
            if unreadable:
                plural = "file" if unreadable == 1 else "files"
                detail += f" ({unreadable} unreadable {plural} ignored)"
            await self._store.update_item(
                item_id, status=ItemStatus.NEEDS_REVIEW, detail=detail
            )
            return

        try:
            result = await self._organise(
                entries,
                ident,
                idempotency_key=f"drop:{job.id}:{item_id}:identified",
            )
        except AutomaticManagementHoldError as hold:
            await self._store.update_item(
                item_id,
                status=ItemStatus.NEEDS_REVIEW,
                detail=(
                    f"Library Management held this album ({hold.reason_code}). "
                    "Fix the profile or provider, then retry the match."
                ),
            )
            return
        await self._finish_item(job, item_id, ident, result, unreadable, staged=entries)

    async def _finish_item(
        self,
        job: DropImportJob,
        item_id: int,
        ident: _Identified,
        result: _OrganiseResult,
        unreadable: int,
        *,
        staged: list[_Entry],
    ) -> None:
        meta = ident.meta
        if result.imported > 0:
            status = ItemStatus.IMPORTED
        elif result.skipped > 0:
            status = ItemStatus.SKIPPED
        else:
            status = ItemStatus.FAILED
        parts: list[str] = []
        if result.imported:
            parts.append(f"imported {result.imported}")
        if result.upgraded:
            parts.append(f"upgraded {result.upgraded} existing files")
        if result.skipped:
            parts.append(f"{result.skipped} already in your library at this quality")
        if result.bonus:
            parts.append(f"{result.bonus} extra files kept alongside the album")
        if unreadable:
            parts.append(
                f"{unreadable} unreadable {'file' if unreadable == 1 else 'files'} ignored"
            )
        await self._store.update_item(
            item_id,
            status=status,
            release_group_mbid=meta.release_group_mbid,
            album_title=meta.album_title,
            artist_name=meta.artist,
            files_imported=result.imported,
            detail=", ".join(parts).capitalize() if parts else None,
            staging_paths=[],
        )
        if result.imported > 0:
            await self._after_import(job, ident)

        # staged sources are consumed by the moves; clear any cross-mount leftovers
        def _tidy() -> None:
            for entry in staged:
                try:
                    entry.path.unlink(missing_ok=True)
                except OSError:
                    pass  # best-effort: sweep_stale removes the directory later

        await asyncio.to_thread(_tidy)

    # -- identification (mirrors the scanner's tiers) --

    async def _read_entries(self, paths: list[Path]) -> tuple[list[_Entry], int]:
        entries: list[_Entry] = []
        unreadable = 0
        for path in paths:
            try:
                tag, info = await asyncio.to_thread(self._tagger.read_tags, path)
                entries.append(_Entry(path=path, tag=tag, info=info))
            except Exception:  # noqa: BLE001 - one bad file must not sink the unit
                unreadable += 1
                logger.warning("Unreadable audio file in drop import: %s", path)
        return entries, unreadable

    @staticmethod
    def _to_local(entry: _Entry) -> LocalTrack:
        tag, info = entry.tag, entry.info
        return LocalTrack(
            path=str(entry.path),
            title=tag.title or "",
            artist=tag.artist or tag.album_artist or "",
            album=tag.album or "",
            track_number=tag.track_number or 0,
            disc_number=tag.disc_number or 1,
            year=tag.year,
            duration_seconds=info.duration_seconds,
            recording_mbid=tag.musicbrainz_recording_id,
        )

    async def _identify(self, entries: list[_Entry]) -> _Identified | None:
        locals_ = [self._to_local(e) for e in entries]

        # Tier 1: consistent MBID tags are authoritative (store purchases are
        # often fully Picard-tagged already).
        tagged_rgs = {
            e.tag.musicbrainz_release_group_id
            for e in entries
            if e.tag.musicbrainz_release_group_id
        }
        if len(tagged_rgs) == 1 and all(
            e.tag.musicbrainz_release_group_id and e.tag.musicbrainz_recording_id
            for e in entries
        ):
            forced = await self._score_against(next(iter(tagged_rgs)), locals_)
            if forced is not None:
                return forced

        if len(entries) >= 2:
            match = await self._try_identify(locals_)
            if match is None:
                enriched, seeds = await self._fingerprint_enrich(entries, locals_)
                if seeds:
                    match = await self._try_identify(enriched, seeds)
                    locals_ = enriched
            if match is not None:
                scored = await self._score_against(match.release_group_mbid, locals_)
                if scored is not None:
                    return scored
            return None

        # Single file: an MBID tag wins, else the fingerprint decides.
        entry = entries[0]
        if entry.tag.musicbrainz_release_group_id:
            return await self._score_against(
                entry.tag.musicbrainz_release_group_id, locals_
            )
        try:
            fp = await self._fingerprinter.fingerprint(entry.path)
        except Exception:  # noqa: BLE001 - no fingerprint just means needs_review
            logger.warning("Fingerprint failed for %s", entry.path)
            return None
        if (
            fp is None
            or fp.status != "pass"
            or (fp.score or 0.0) < _FINGERPRINT_SCORE_THRESHOLD
            or not fp.recording_id
        ):
            return None
        rg = await self._mb_matcher.resolve_recording_to_release_group(fp.recording_id)
        if not rg:
            return None
        locals_ = [msgspec.structs.replace(locals_[0], recording_mbid=fp.recording_id)]
        return await self._score_against(rg, locals_)

    async def _try_identify(
        self, locals_: list[LocalTrack], seeds: list[str] | None = None
    ) -> "AlbumMatch | None":
        try:
            match = await self._identifier.identify(locals_, seed_release_groups=seeds)
        except Exception as exc:  # noqa: BLE001 - identification falls back to review
            logger.warning("Album identification failed: %s", exc)
            return None
        return match if match is not None and match.accepted else None

    async def _score_against(
        self, release_group_mbid: str, locals_: list[LocalTrack]
    ) -> _Identified | None:
        picked = await self._identifier.release_tracks(release_group_mbid, len(locals_))
        if picked is None:
            return None
        meta, tracks = picked
        match = score_release(locals_, tracks, meta)
        return _Identified(meta=meta, tracks=tracks, match=match)

    async def _fingerprint_enrich(
        self, entries: list[_Entry], locals_: list[LocalTrack]
    ) -> tuple[list[LocalTrack], list[str]]:
        """The scanner's audio-backed second attempt: fingerprint every file
        (fail-open per file), enrich locals with confirmed recordings, and
        collect the distinct release groups as matcher seeds."""
        enriched: list[LocalTrack] = []
        seeds: list[str] = []
        seen: set[str] = set()
        for entry, local in zip(entries, locals_):
            try:
                fp: "FingerprintResult" = await self._fingerprinter.fingerprint(
                    entry.path
                )
                if (
                    fp.status == "pass"
                    and (fp.score or 0.0) >= _FINGERPRINT_SCORE_THRESHOLD
                    and fp.recording_id
                ):
                    local = msgspec.structs.replace(
                        local, recording_mbid=fp.recording_id
                    )
                    rg = await self._mb_matcher.resolve_recording_to_release_group(
                        fp.recording_id
                    )
                    if rg and rg not in seen:
                        seen.add(rg)
                        seeds.append(rg)
            except Exception as exc:  # noqa: BLE001 - one bad file degrades to tag-only
                logger.warning("Fingerprint/resolve failed for %s: %s", entry.path, exc)
            enriched.append(local)
        return enriched, seeds

    # -- organisation (mirrors the download import) --

    def _require_library_root(self) -> Path:
        lib = self._prefs.get_typed_library_settings_raw()
        if not lib.library_roots:
            raise ValidationError("Set a library path before importing.")
        return Path(lib.library_roots[0].path)

    async def _organise(
        self,
        entries: list[_Entry],
        ident: _Identified,
        confidence_override: float | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> _OrganiseResult:
        root = self._require_library_root()
        lib = self._prefs.get_typed_library_settings_raw()
        template = lib.naming_template or NamingTemplateEngine.DEFAULT
        meta, tracks, match = ident.meta, ident.tracks, ident.match
        confidence = (
            confidence_override
            if confidence_override is not None
            else max(0.0, round(1.0 - match.distance, 4))
        )
        track_by_recording = {t.recording_mbid: t for t in tracks if t.recording_mbid}

        if self._publish_import_bundle is None or self._policy_revision_getter is None:
            raise RuntimeError("The shared drop import publisher is not configured.")
        if idempotency_key is None:
            raise RuntimeError("A shared drop import needs a durable source ID.")
        return await self._organise_shared(
            entries,
            ident,
            root,
            template,
            confidence,
            track_by_recording,
            idempotency_key=idempotency_key,
        )

    async def _organise_shared(
        self,
        entries: list[_Entry],
        ident: _Identified,
        root: Path,
        template: str,
        confidence: float,
        track_by_recording: dict[str, MBTrack],
        *,
        idempotency_key: str,
    ) -> _OrganiseResult:
        publisher = self._publish_import_bundle
        revision_getter = self._policy_revision_getter
        if publisher is None or revision_getter is None:
            raise RuntimeError("The shared drop import publisher is not configured.")
        meta, match = ident.meta, ident.match
        planned: list[_PlannedDropImport] = []
        skipped = 0
        for entry in entries:
            recording = match.assignments.get(str(entry.path))
            track = track_by_recording.get(recording) if recording else None
            value = (
                await self._plan_shared_mapped(
                    entry, meta, track, root, template, confidence
                )
                if track is not None
                else self._plan_shared_bonus(entry, meta, root, template)
            )
            if value is None:
                skipped += 1
            else:
                planned.append(value)
        if not planned:
            return _OrganiseResult(imported=0, upgraded=0, skipped=skipped, bonus=0)

        settings = self._prefs.get_typed_library_settings_raw()
        roots = {
            Path(value.path).resolve(strict=False): value.id
            for value in settings.library_roots
        }
        root_id = roots.get(root.resolve(strict=False))
        if root_id is None:
            raise RuntimeError("Import target does not resolve to one library root.")
        policy = self._prefs.get_download_policy()
        recycle_bin = resolve_bin_path(
            policy.recycle_bin_path, [value.path for value in settings.library_roots]
        )
        requests: list[LibraryManagementImportFile] = []
        for ordinal, value in enumerate(planned):
            replacement_track_id = replacement_root_id = replacement_relative = None
            recycle_bin_path = None
            if value.replacement is not None:
                if recycle_bin is None:
                    raise RuntimeError("An import replacement requires a recycle bin.")
                replacement_track_id = str(value.replacement["id"])
                replacement_root_id = str(value.replacement["root_id"])
                replacement_relative = str(value.replacement["relative_path"])
                recycle_bin_path = str(recycle_bin)
            requests.append(
                LibraryManagementImportFile(
                    ordinal=ordinal,
                    input_path=str(value.entry.path),
                    destination_root_id=root_id,
                    destination_relative_path=value.target.relative_to(root).as_posix(),
                    tag=value.tag,
                    info=value.entry.info,
                    release_group_mbid=meta.release_group_mbid,
                    release_mbid=meta.release_mbid,
                    recording_mbid=value.recording_mbid,
                    release_track_mbid=value.release_track_mbid,
                    medium_position=value.medium_position,
                    release_track_position=value.release_track_position,
                    authoritative_mapping=value.authoritative_mapping,
                    confidence=value.confidence,
                    source=_SOURCE,
                    source_path=str(value.entry.path),
                    replacement_local_track_id=replacement_track_id,
                    replacement_root_id=replacement_root_id,
                    replacement_relative_path=replacement_relative,
                    recycle_bin_path=recycle_bin_path,
                )
            )
        digest = hashlib.sha256(
            "\n".join(
                f"{value.entry.path.resolve(strict=False)}\0"
                f"{value.target.resolve(strict=False)}"
                for value in planned
            ).encode()
        ).hexdigest()
        await publisher(
            LibraryManagementImportBundle(
                idempotency_key=(
                    f"{idempotency_key}:{meta.release_group_mbid}:{digest}"
                ),
                origin="drop_import",
                policy_revision=revision_getter(),
                files=tuple(requests),
            )
        )
        return _OrganiseResult(
            imported=len(planned),
            upgraded=sum(value.replacement is not None for value in planned),
            skipped=skipped,
            bonus=sum(value.bonus for value in planned),
        )

    async def _plan_shared_mapped(
        self,
        entry: _Entry,
        meta,  # noqa: ANN001 - album_matcher._ReleaseMeta
        track: MBTrack,
        root: Path,
        template: str,
        confidence: float,
    ) -> _PlannedDropImport | None:
        target_tag = self._target_tag(meta, track, entry.tag)
        replacement = None
        present = await self._library.get_file_at_position(
            meta.release_group_mbid,
            target_tag.disc_number or 1,
            target_tag.track_number,
        )
        if present is not None and row_covers_track(
            present,
            recording_mbid=track.recording_mbid,
            title=track.title,
            duration_seconds=entry.info.duration_seconds,
        ):
            new_rank = tier_rank(tier_for(entry.info.file_format, entry.info.bitrate))
            old_rank = tier_rank(
                tier_for(present.get("file_format") or "", present.get("bit_rate"))
            )
            settings = self._prefs.get_typed_library_settings_raw()
            recycle_bin = resolve_bin_path(
                self._prefs.get_download_policy().recycle_bin_path,
                [value.path for value in settings.library_roots],
            )
            if new_rank <= old_rank or recycle_bin is None:
                return None
            replacement = present
        target = root / self._naming.format_path(
            template, target_tag, entry.info.file_format
        )
        if target.exists() and (
            replacement is None or Path(replacement["file_path"]) != target
        ):
            return None
        return _PlannedDropImport(
            entry=entry,
            target=target,
            tag=target_tag,
            recording_mbid=track.recording_mbid,
            release_track_mbid=track.release_track_mbid,
            medium_position=track.disc,
            release_track_position=track.position,
            authoritative_mapping=True,
            confidence=confidence,
            replacement=replacement,
            bonus=False,
        )

    def _plan_shared_bonus(
        self,
        entry: _Entry,
        meta,  # noqa: ANN001 - album_matcher._ReleaseMeta
        root: Path,
        template: str,
    ) -> _PlannedDropImport | None:
        target_tag = self._target_tag(meta, None, entry.tag)
        target = root / self._naming.format_path(
            template, target_tag, entry.info.file_format
        )
        if target.exists():
            return None
        return _PlannedDropImport(
            entry=entry,
            target=target,
            tag=target_tag,
            recording_mbid=None,
            release_track_mbid=None,
            medium_position=None,
            release_track_position=None,
            authoritative_mapping=False,
            confidence=_UNMAPPED_CONFIDENCE,
            replacement=None,
            bonus=True,
        )

    @staticmethod
    def _target_tag(
        meta,  # noqa: ANN001 - album_matcher._ReleaseMeta
        track: MBTrack | None,
        file_tag: "AudioTag",
    ) -> "AudioTag":
        from models.audio import AudioTag

        album_artist = "Various Artists" if meta.is_various else (meta.artist or None)
        return AudioTag(
            title=(track.title if track else None) or file_tag.title or "",
            artist=file_tag.artist or meta.artist or "",
            album=meta.album_title,
            album_artist=album_artist,
            track_number=track.position if track else (file_tag.track_number or 0),
            disc_number=(track.disc if track else file_tag.disc_number) or 1,
            year=meta.year or file_tag.year,
            genre=file_tag.genre,
            genres=list(file_tag.genres),
            musicbrainz_release_group_id=meta.release_group_mbid,
            musicbrainz_release_id=meta.release_mbid,
            musicbrainz_recording_id=(
                (track.recording_mbid if track else None)
                or file_tag.musicbrainz_recording_id
            ),
            musicbrainz_artist_id=file_tag.musicbrainz_artist_id,
            musicbrainz_album_artist_id=meta.artist_mbid,
            acoustid_id=file_tag.acoustid_id,
            compilation=file_tag.compilation or meta.is_various,
        )

    # -- post-import hooks --

    async def _after_import(self, job: DropImportJob, ident: _Identified) -> None:
        meta = ident.meta
        rg = meta.release_group_mbid
        try:
            await self._on_import(
                mbid=rg,
                artist_mbid=meta.artist_mbid,
                artist_name=meta.artist,
                title=meta.album_title,
                year=meta.year,
            )
        except Exception:  # noqa: BLE001 - invalidation is best-effort
            logger.warning("Import invalidation failed for %s", rg)

        record = None
        try:
            record = await self._requests.async_get_record(rg)
            if record is not None and record.status != "imported":
                await self._requests.async_update_status(
                    rg,
                    "imported",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:  # noqa: BLE001 - request sync must never fail the import
            logger.warning("Could not sync request state for %s", rg)

        try:
            watch = await self._wanted.get_watch(rg)
            if watch is not None:
                await self._wanted.mark_fulfilled(rg, "satisfied")
        except Exception:  # noqa: BLE001 - the watcher reconciles later
            logger.warning("Could not fulfil wanted watch for %s", rg)

        if record is not None and record.user_id and record.user_id != job.user_id:
            try:
                await self._sse.publish(
                    f"user:{record.user_id}",
                    "request_imported",
                    {
                        "event_id": uuid.uuid4().hex,
                        "release_group_mbid": rg,
                        "artist_name": meta.artist,
                        "album_title": meta.album_title,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - notification is best-effort
                logger.debug("request_imported publish failed: %s", exc)

    async def _publish_job(self, job: DropImportJob) -> None:
        try:
            await self._sse.publish(
                f"user:{job.user_id}",
                "drop_import_updated",
                {"event_id": uuid.uuid4().hex, "job_id": job.id},
            )
        except Exception as exc:  # noqa: BLE001 - progress push is best-effort
            logger.debug("drop_import_updated publish failed: %s", exc)

    async def _owned_item(
        self, item_id: int, user_id: str, is_admin: bool
    ) -> tuple[DropImportItem, DropImportJob]:
        item = await self._store.get_item(item_id)
        if item is None:
            raise ResourceNotFoundError("Import item not found")
        job = await self._store.get_job(item.job_id)
        if job is None or (job.user_id != user_id and not is_admin):
            raise ResourceNotFoundError("Import item not found")
        return item, job
