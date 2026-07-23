"""Fresh, explicit previews for resolving one Library Management collision."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import unicodedata
import uuid

import msgspec

from api.v1.schemas.library_management import settings_revision
from api.v1.schemas.library_management_preview import (
    LibraryManagementDuplicateResolutionPreviewRequest,
    LibraryManagementPreviewCreatedResponse,
)
from core.exceptions import (
    ConflictError,
    ResourceNotFoundError,
    StaleRevisionError,
    ValidationError,
)
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.audio_metadata import DesiredAudioDocument
from models.library_management import (
    DUPLICATE_CHANGED,
    FILE_CHANGED,
    MANAGEMENT_RECYCLE_ROOT_ID,
    PATH_COLLISION_DIFFERENT,
    RECYCLE_UNAVAILABLE,
    SIDECAR_COLLISION,
    LibraryManagementJobSnapshot,
    LibraryManagementPlanItem,
)
from models.library_management_planning import PinnedLibraryManagementProfile
from models.library_work import OperationJob
from services.native.library_filesystem_coordinator import LibraryFilesystemCoordinator
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.preferences_service import PreferencesService

_DUPLICATE_NAMESPACE = uuid.UUID("e06cf0b4-1704-4f78-a501-8472cb14f95f")
_MAX_DIRECTORY_ENTRIES = 10_000


def _json(value: object) -> str:
    return json.dumps(
        msgspec.to_builtins(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _collision_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _token(job_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{job_id}\x00{idempotency_key}".encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class LibraryManagementDuplicateService:
    def __init__(
        self,
        store: NativeLibraryStore,
        preferences: PreferencesService,
        filesystem: LibraryFilesystemCoordinator,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._preferences = preferences
        self._filesystem = filesystem
        self._clock = clock

    async def create_preview(
        self,
        request: LibraryManagementDuplicateResolutionPreviewRequest,
        actor_user_id: str,
    ) -> LibraryManagementPreviewCreatedResponse:
        self._validate_request(request)
        source_job = await self._store.get_operation_job(request.source_job_id)
        source_snapshot = await self._store.get_library_management_job_snapshot(
            request.source_job_id
        )
        source_item = await self._store.get_library_management_plan_item(
            request.source_job_id, request.source_plan_item_ordinal
        )
        if source_job is None or source_snapshot is None or source_item is None:
            raise ResourceNotFoundError("Library Management collision not found.")
        if str(source_job["state"]) not in {
            "ready",
            "succeeded",
            "stopped",
            "failed",
        }:
            raise ValidationError(
                "The source operation is not ready for collision resolution."
            )
        if (
            int(source_job["row_revision"])
            != request.expected_source_operation_row_revision
        ):
            raise StaleRevisionError(
                "The source operation changed before collision resolution."
            )

        settings = self._preferences.get_library_management_settings_raw()
        management_revision = settings_revision(settings)
        if management_revision != request.expected_settings_revision:
            raise StaleRevisionError(
                "Library management settings changed before collision resolution."
            )
        policy = LibraryPolicyResolver(
            self._preferences.get_typed_library_settings_raw()
        )
        if policy.policy_revision != request.expected_policy_revision:
            raise StaleRevisionError(
                "Library policy changed before collision resolution."
            )
        if source_snapshot.settings_revision != management_revision:
            raise StaleRevisionError(
                "Run a new management preview before resolving this collision."
            )
        pinned = msgspec.json.decode(
            source_snapshot.profile_snapshot_json.encode(),
            type=PinnedLibraryManagementProfile,
        )
        current_profile = next(
            (value for value in settings.profiles if value.id == pinned.profile.id),
            None,
        )
        if (
            current_profile is None
            or current_profile.revision != pinned.profile.revision
        ):
            raise StaleRevisionError(
                "The management profile changed before collision resolution."
            )
        pinned = msgspec.structs.replace(
            pinned, recycle_bin_path=settings.recycle_bin_path
        )

        now = self._clock()
        job_id = str(uuid.uuid5(_DUPLICATE_NAMESPACE, request.idempotency_key))
        preview_token = _token(job_id, request.idempotency_key)
        catalog_revision = await self._store.get_catalog_revision()
        selection = msgspec.to_builtins(request)
        snapshot = LibraryManagementJobSnapshot(
            job_id=job_id,
            mode="duplicate_resolution",
            origin="manual",
            phase="planning",
            selection_json=_json(selection),
            profile_revision=pinned.profile.revision,
            settings_revision=management_revision,
            naming_revision=pinned.naming_script.revision,
            policy_revision=policy.policy_revision,
            catalog_revision=catalog_revision,
            profile_snapshot_json=msgspec.json.encode(pinned).decode(),
            preview_token_hash=hashlib.sha256(preview_token.encode()).hexdigest(),
            preview_created_at=now,
            preview_expires_at=now + settings.preview_retention_hours * 60 * 60,
            linked_operation_job_id=request.source_job_id,
            created_at=now,
            updated_at=now,
        )
        existing_id, created = await self._store.create_library_management_job(
            OperationJob(
                id=job_id,
                kind="library_management",
                requested_by_user_id=actor_user_id,
                input_catalog_revision=catalog_revision,
                idempotency_key=request.idempotency_key,
                created_at=now,
            ),
            snapshot,
        )
        if not created:
            existing = await self._store.get_library_management_job_snapshot(
                existing_id
            )
            existing_job = await self._store.get_operation_job(existing_id)
            if (
                existing is None
                or existing_job is None
                or existing.mode != "duplicate_resolution"
                or existing.selection_json != snapshot.selection_json
                or existing.preview_token_hash != snapshot.preview_token_hash
                or existing_job["requested_by_user_id"] != actor_user_id
            ):
                raise ConflictError(
                    "The idempotency key belongs to another duplicate resolution."
                )
            return LibraryManagementPreviewCreatedResponse(
                job_id=existing_id,
                preview_token=preview_token,
                created_at=existing.preview_created_at or existing.created_at,
                expires_at=existing.preview_expires_at or existing.created_at,
                existing=True,
            )
        return LibraryManagementPreviewCreatedResponse(
            job_id=job_id,
            preview_token=preview_token,
            created_at=now,
            expires_at=now + settings.preview_retention_hours * 60 * 60,
        )

    async def run_claimed_preview(self, job: dict, worker_id: str) -> None:
        job_id = str(job["id"])
        snapshot = await self._store.get_library_management_job_snapshot(job_id)
        if (
            snapshot is None
            or snapshot.mode != "duplicate_resolution"
            or snapshot.phase != "planning"
        ):
            raise ValidationError(
                "The claimed operation is not a duplicate-resolution preview."
            )
        request = msgspec.convert(
            json.loads(snapshot.selection_json),
            type=LibraryManagementDuplicateResolutionPreviewRequest,
        )
        source_job = await self._store.get_operation_job(request.source_job_id)
        if (
            source_job is None
            or int(source_job["row_revision"])
            != request.expected_source_operation_row_revision
        ):
            raise StaleRevisionError(
                "The source operation changed during collision planning."
            )
        items = await self._plan_items(snapshot, request)
        revision = await self._store.append_library_management_plan_items(
            job_id,
            items,
            expected_snapshot_revision=snapshot.row_revision,
        )
        await self._store.finalize_library_management_preview(
            job_id,
            worker_id,
            expected_snapshot_revision=revision,
            now=self._clock(),
        )

    async def _plan_items(
        self,
        snapshot: LibraryManagementJobSnapshot,
        request: LibraryManagementDuplicateResolutionPreviewRequest,
    ) -> list[LibraryManagementPlanItem]:
        original = await self._store.get_library_management_plan_item(
            request.source_job_id, request.source_plan_item_ordinal
        )
        if original is None or original.local_track_id is None:
            raise ResourceNotFoundError("Library Management collision not found.")
        source_track = await self._store.get_target_track(original.local_track_id)
        if source_track is None:
            return [self._blocked_from(original, snapshot, FILE_CHANGED)]

        policy = LibraryPolicyResolver(
            self._preferences.get_typed_library_settings_raw()
        )
        roots = {value.id: Path(value.path) for value in policy.settings.library_roots}
        source_root = roots.get(str(source_track["root_id"]))
        existing_root = roots.get(request.existing_root_id)
        if source_root is None or existing_root is None:
            return [self._blocked_from(original, snapshot, DUPLICATE_CHANGED)]
        source = self._safe_path(source_root, str(source_track["relative_path"]))
        existing = self._safe_path(existing_root, request.existing_relative_path)
        source_fingerprint = "missing"
        existing_fingerprint = "missing"
        reason: str | None = None
        try:
            async with self._filesystem.read_many(
                {str(source_track["root_id"]), request.existing_root_id}
            ):
                source_fingerprint = await asyncio.to_thread(self._hash_file, source)
                existing_fingerprint = await asyncio.to_thread(
                    self._hash_file, existing
                )
        except (OSError, ValidationError):
            reason = DUPLICATE_CHANGED
        if (
            str(source_track["root_id"]) != original.expected_root_id
            or str(source_track["relative_path"]) != original.expected_relative_path
            or str(source_track["stat_revision"]) != original.expected_stat_revision
            or str(source_track["tag_revision"] or "") != original.expected_tag_revision
            or source_fingerprint != original.expected_file_fingerprint
        ):
            reason = FILE_CHANGED
        exact_content = source_fingerprint == existing_fingerprint
        if (
            request.collision_kind == "same_path_same_content" and not exact_content
        ) or (
            request.collision_kind
            in {
                "same_path_different_content",
                "same_release_position_different_content",
            }
            and exact_content
        ):
            reason = DUPLICATE_CHANGED

        existing_track = await self._store.get_target_track_by_path(str(existing))
        if request.existing_local_track_id is not None and (
            existing_track is None
            or str(existing_track["id"]) != request.existing_local_track_id
        ):
            reason = DUPLICATE_CHANGED
        if (
            existing_track is not None
            and str(existing_track["id"]) == original.local_track_id
        ):
            reason = DUPLICATE_CHANGED
        if not await self._collision_is_current(
            request,
            original,
            source_track,
            existing_track,
        ):
            reason = DUPLICATE_CHANGED

        source_item = await self._fresh_item(
            snapshot,
            original,
            source_track,
            source_fingerprint,
            ordinal=0,
        )
        evidence = {
            "action": request.action,
            "source_job_id": request.source_job_id,
            "source_plan_item_ordinal": request.source_plan_item_ordinal,
            "collision_kind": request.collision_kind,
            "existing_root_id": request.existing_root_id,
            "existing_relative_path": request.existing_relative_path,
            "existing_file_fingerprint": existing_fingerprint,
            "existing_local_track_id": (
                str(existing_track["id"]) if existing_track is not None else None
            ),
            "exact_content": exact_content,
        }
        if reason is not None:
            return [
                msgspec.structs.replace(
                    source_item,
                    eligibility="stale",
                    reason_code=reason,
                    collision_json=_json([evidence]),
                )
            ]

        if request.action == "keep_existing":
            desired = DesiredAudioDocument(fields=())
            diff = {
                "requires_write": False,
                "tags_changed": False,
                "artwork_changed": False,
                "path_changed": False,
                "sidecars_changed": False,
                "duplicate_resolution": evidence,
            }
            desired_json = msgspec.json.encode(desired).decode()
            return [
                msgspec.structs.replace(
                    source_item,
                    destination_root_id=source_item.expected_root_id,
                    destination_relative_path=source_item.expected_relative_path,
                    destination_collision_key=_collision_key(
                        source_item.expected_relative_path
                    ),
                    desired_document_json=desired_json,
                    desired_document_hash=hashlib.sha256(
                        desired_json.encode()
                    ).hexdigest(),
                    artwork_choices_json="[]",
                    diff_json=_json(diff),
                    collision_json=_json([evidence]),
                    estimated_temporary_bytes=0,
                )
            ]

        recycle = self._recycle_root(snapshot)
        if request.action.startswith("recycle_") and recycle is None:
            return [
                msgspec.structs.replace(
                    source_item,
                    eligibility="blocked",
                    reason_code=RECYCLE_UNAVAILABLE,
                    collision_json=_json([evidence]),
                )
            ]

        if request.action == "recycle_incoming_keep_existing":
            assert recycle is not None
            return [
                await self._recycle_item(
                    snapshot,
                    source_item,
                    source_track,
                    source_fingerprint,
                    recycle,
                    evidence,
                    ordinal=0,
                )
            ]

        if request.action == "keep_incoming_alternate":
            assert request.alternate_relative_path is not None
            updated = self._with_destination(
                source_item,
                request.alternate_relative_path,
                evidence,
            )
            return [self._validate_outputs(updated, roots, allowed=None)]

        assert request.action == "recycle_existing_keep_incoming"
        assert recycle is not None
        incoming = self._with_destination(
            source_item,
            str(original.destination_relative_path),
            evidence,
        )
        incoming = self._validate_outputs(
            incoming,
            roots,
            allowed=(request.existing_root_id, request.existing_relative_path),
        )
        if incoming.eligibility == "blocked":
            return [incoming]
        if existing_track is None:
            diff = json.loads(incoming.diff_json)
            diff["recycle_untracked_collision"] = {
                **evidence,
                "recycle_relative_path": self._recycle_relative(
                    snapshot.job_id, existing
                ),
            }
            return [
                msgspec.structs.replace(
                    incoming,
                    diff_json=_json(diff),
                )
            ]

        loser = await self._fresh_item(
            snapshot,
            original,
            existing_track,
            existing_fingerprint,
            ordinal=0,
        )
        loser = await self._recycle_item(
            snapshot,
            loser,
            existing_track,
            existing_fingerprint,
            recycle,
            evidence,
            ordinal=0,
        )
        return [loser, msgspec.structs.replace(incoming, ordinal=1)]

    async def _fresh_item(
        self,
        snapshot: LibraryManagementJobSnapshot,
        original: LibraryManagementPlanItem,
        track: dict,
        fingerprint: str,
        *,
        ordinal: int,
    ) -> LibraryManagementPlanItem:
        album_id = str(track["local_album_id"])
        track_id = str(track["id"])
        identity = await self._store.get_accepted_library_management_identity(
            album_id, local_track_ids=(track_id,)
        )
        mapped = (
            identity.tracks[0] if identity is not None and identity.tracks else None
        )
        _album, album_revision = await self._store.list_management_overrides(
            subject_kind="album", subject_id=album_id
        )
        _track, track_revision = await self._store.list_management_overrides(
            subject_kind="track", subject_id=track_id
        )
        override_revision = hashlib.sha256(
            f"{album_revision}\x00{track_revision}".encode()
        ).hexdigest()
        reason = None
        if (
            identity is None
            or identity.identity_revision is None
            or identity.release_mbid is None
            or mapped is None
            or mapped.identity_revision is None
            or mapped.recording_mbid is None
            or mapped.release_track_mbid is None
        ):
            reason = DUPLICATE_CHANGED
        return LibraryManagementPlanItem(
            job_id=snapshot.job_id,
            ordinal=ordinal,
            bundle_ordinal=0,
            local_album_id=album_id,
            local_track_id=track_id,
            expected_album_revision=(identity.album_revision if identity else None),
            expected_track_revision=int(track["row_revision"]),
            expected_identity_revision=(mapped.identity_revision if mapped else None),
            expected_album_identity_revision=(
                identity.identity_revision if identity else None
            ),
            expected_override_revision=override_revision,
            expected_catalog_revision=snapshot.catalog_revision,
            expected_policy_revision=snapshot.policy_revision,
            expected_profile_revision=snapshot.profile_revision,
            expected_root_id=str(track["root_id"]),
            expected_relative_path=str(track["relative_path"]),
            expected_stat_revision=str(track["stat_revision"]),
            expected_tag_revision=str(track["tag_revision"] or ""),
            expected_file_fingerprint=fingerprint,
            source_path_identity=hashlib.sha256(
                f"{track['root_id']}\x00{track['relative_path']}".encode()
            ).hexdigest(),
            destination_root_id=original.destination_root_id,
            destination_relative_path=original.destination_relative_path,
            destination_collision_key=original.destination_collision_key,
            desired_document_json=original.desired_document_json,
            desired_document_hash=original.desired_document_hash,
            artwork_choices_json=original.artwork_choices_json,
            diff_json=original.diff_json,
            capability_json=original.capability_json,
            collision_json=original.collision_json,
            eligibility="stale" if reason else "eligible",
            reason_code=reason,
            estimated_temporary_bytes=int(track["file_size_bytes"] or 0),
            created_at=self._clock(),
        )

    async def _recycle_item(
        self,
        snapshot: LibraryManagementJobSnapshot,
        item: LibraryManagementPlanItem,
        track: dict,
        fingerprint: str,
        recycle: Path,
        evidence: dict,
        *,
        ordinal: int,
    ) -> LibraryManagementPlanItem:
        source = Path(str(track["file_path"]))
        relative = self._recycle_relative(snapshot.job_id, source)
        destination = self._safe_path(recycle, relative)
        if destination.exists() or destination.is_symlink():
            return msgspec.structs.replace(
                item,
                eligibility="blocked",
                reason_code=RECYCLE_UNAVAILABLE,
                collision_json=_json([evidence]),
            )
        desired = DesiredAudioDocument(fields=())
        desired_json = msgspec.json.encode(desired).decode()
        resolution = {
            **evidence,
            "recycle_relative_path": relative,
            "recycled_file_fingerprint": fingerprint,
        }
        diff = {
            "requires_write": True,
            "tags_changed": False,
            "artwork_changed": False,
            "path_changed": True,
            "sidecars_changed": False,
            "duplicate_recycle_only": True,
            "duplicate_resolution": resolution,
        }
        return msgspec.structs.replace(
            item,
            ordinal=ordinal,
            destination_root_id=MANAGEMENT_RECYCLE_ROOT_ID,
            destination_relative_path=relative,
            destination_collision_key=_collision_key(relative),
            desired_document_json=desired_json,
            desired_document_hash=hashlib.sha256(desired_json.encode()).hexdigest(),
            artwork_choices_json="[]",
            diff_json=_json(diff),
            capability_json=_json(
                {"audio_format": str(track["file_format"]), "recycle_only": True}
            ),
            collision_json=_json([resolution]),
            eligibility="eligible",
            reason_code=None,
            estimated_temporary_bytes=int(track["file_size_bytes"] or 0),
        )

    def _with_destination(
        self,
        item: LibraryManagementPlanItem,
        relative: str,
        evidence: dict,
    ) -> LibraryManagementPlanItem:
        safe_relative = self._safe_relative(relative)
        if (
            PurePosixPath(safe_relative).suffix.casefold()
            != PurePosixPath(item.expected_relative_path).suffix.casefold()
        ):
            raise ValidationError(
                "An alternate duplicate path must preserve the audio extension."
            )
        diff = json.loads(item.diff_json)
        old_relative = str(item.destination_relative_path)
        old_parent = PurePosixPath(old_relative).parent
        new_parent = PurePosixPath(safe_relative).parent
        diff.update(
            {
                "requires_write": True,
                "path_changed": (
                    item.expected_root_id != item.destination_root_id
                    or item.expected_relative_path != safe_relative
                ),
                "destination_relative_path": safe_relative,
                "duplicate_resolution": evidence,
            }
        )
        artwork = json.loads(item.artwork_choices_json)
        for choice in artwork:
            output = choice.get("destination_relative_path")
            if not output:
                continue
            output_path = PurePosixPath(str(output))
            try:
                tail = output_path.relative_to(old_parent)
            except ValueError:
                continue
            choice["destination_relative_path"] = (new_parent / tail).as_posix()
        return msgspec.structs.replace(
            item,
            destination_relative_path=safe_relative,
            destination_collision_key=_collision_key(safe_relative),
            artwork_choices_json=_json(artwork),
            diff_json=_json(diff),
            collision_json=_json([evidence]),
            eligibility="eligible",
            reason_code=None,
        )

    def _validate_outputs(
        self,
        item: LibraryManagementPlanItem,
        roots: dict[str, Path],
        *,
        allowed: tuple[str, str] | None,
    ) -> LibraryManagementPlanItem:
        root_id = item.destination_root_id or item.expected_root_id
        root = roots.get(root_id)
        if root is None or item.destination_relative_path is None:
            return msgspec.structs.replace(
                item, eligibility="blocked", reason_code=DUPLICATE_CHANGED
            )
        candidates = [(item.destination_relative_path, "audio")]
        destination_parent = PurePosixPath(item.destination_relative_path).parent
        for sidecar in json.loads(item.diff_json).get("sidecars", []):
            candidates.append(
                (
                    (
                        destination_parent / str(sidecar["destination_relative_path"])
                    ).as_posix(),
                    "sidecar",
                )
            )
        for choice in json.loads(item.artwork_choices_json):
            relative = choice.get("destination_relative_path")
            if relative:
                candidates.append((str(relative), "sidecar"))
        seen: set[str] = set()
        for relative, kind in candidates:
            key = _collision_key(relative)
            if key in seen:
                return msgspec.structs.replace(
                    item, eligibility="blocked", reason_code=SIDECAR_COLLISION
                )
            seen.add(key)
            path = self._safe_path(root, relative)
            if path == self._safe_path(
                roots[item.expected_root_id], item.expected_relative_path
            ):
                continue
            if allowed == (root_id, relative):
                continue
            if path.exists() or path.is_symlink() or self._normalized_sibling(path):
                return msgspec.structs.replace(
                    item,
                    eligibility="blocked",
                    reason_code=(
                        PATH_COLLISION_DIFFERENT
                        if kind == "audio"
                        else SIDECAR_COLLISION
                    ),
                )
        return item

    async def _collision_is_current(
        self,
        request: LibraryManagementDuplicateResolutionPreviewRequest,
        original: LibraryManagementPlanItem,
        source_track: dict,
        existing_track: dict | None,
    ) -> bool:
        destination_root_id = original.destination_root_id or original.expected_root_id
        destination_relative = original.destination_relative_path
        if destination_relative is None:
            return False
        if request.collision_kind in {
            "same_path_same_content",
            "same_path_different_content",
            "destination_created_after_preview",
        }:
            return (
                request.existing_root_id == destination_root_id
                and request.existing_relative_path == destination_relative
            )
        if request.collision_kind == "normalized_path_collision":
            return (
                request.existing_root_id == destination_root_id
                and request.existing_relative_path != destination_relative
                and _collision_key(request.existing_relative_path)
                == _collision_key(destination_relative)
            )
        if request.collision_kind == "sidecar_collision":
            planned_sidecars = json.loads(original.diff_json).get("sidecars", [])
            destination_parent = PurePosixPath(destination_relative).parent
            return request.existing_root_id == destination_root_id and any(
                value.get("destination_collision")
                and (
                    destination_parent / str(value.get("destination_relative_path", ""))
                ).as_posix()
                == request.existing_relative_path
                for value in planned_sidecars
            )
        if (
            request.collision_kind != "same_release_position_different_content"
            or existing_track is None
        ):
            return False
        source_identity = await self._store.get_accepted_library_management_identity(
            str(source_track["local_album_id"]),
            local_track_ids=(str(source_track["id"]),),
        )
        existing_identity = await self._store.get_accepted_library_management_identity(
            str(existing_track["local_album_id"]),
            local_track_ids=(str(existing_track["id"]),),
        )
        source_mapping = (
            source_identity.tracks[0]
            if source_identity is not None and source_identity.tracks
            else None
        )
        existing_mapping = (
            existing_identity.tracks[0]
            if existing_identity is not None and existing_identity.tracks
            else None
        )
        return bool(
            source_mapping is not None
            and existing_mapping is not None
            and source_mapping.release_mbid
            and source_mapping.release_mbid == existing_mapping.release_mbid
            and source_mapping.release_track_mbid
            and source_mapping.release_track_mbid == existing_mapping.release_track_mbid
        )

    def _recycle_root(self, snapshot: LibraryManagementJobSnapshot) -> Path | None:
        pinned = msgspec.json.decode(
            snapshot.profile_snapshot_json.encode(),
            type=PinnedLibraryManagementProfile,
        )
        if not pinned.recycle_bin_path:
            return None
        root = Path(pinned.recycle_bin_path)
        try:
            metadata = root.lstat()
        except OSError:
            return None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or not os.access(root, os.W_OK | os.X_OK)
        ):
            return None
        return root

    @staticmethod
    def _recycle_relative(job_id: str, source: Path) -> str:
        digest = hashlib.sha256(str(source).encode()).hexdigest()[:16]
        name = source.name or "recycled-file"
        return f"{job_id}/{digest}-{name}"

    @staticmethod
    def _validate_request(
        request: LibraryManagementDuplicateResolutionPreviewRequest,
    ) -> None:
        if not request.idempotency_key.strip():
            raise ValidationError("A duplicate-resolution idempotency key is required.")
        if request.source_plan_item_ordinal < 0:
            raise ValidationError("A source plan item ordinal cannot be negative.")
        if request.action == "keep_incoming_alternate":
            if request.alternate_relative_path is None:
                raise ValidationError("An explicit alternate path is required.")
        elif request.alternate_relative_path is not None:
            raise ValidationError(
                "An alternate path is valid only when keeping incoming under that path."
            )
        LibraryManagementDuplicateService._safe_relative(request.existing_relative_path)

    @staticmethod
    def _safe_relative(value: str) -> str:
        pure = PurePosixPath(value)
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in {"", ".", ".."} for part in pure.parts)
            or "\x00" in value
        ):
            raise ValidationError("A duplicate-resolution path is unsafe.")
        return pure.as_posix()

    @classmethod
    def _safe_path(cls, root: Path, relative: str) -> Path:
        pure = PurePosixPath(cls._safe_relative(relative))
        metadata = root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValidationError("A duplicate-resolution root is unsafe.")
        current = root
        for part in pure.parts[:-1]:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValidationError("A duplicate-resolution path contains a symlink.")
        return root.joinpath(*pure.parts)

    @staticmethod
    def _normalized_sibling(path: Path) -> bool:
        if not path.parent.is_dir():
            return False
        wanted = _collision_key(path.name)
        with os.scandir(path.parent) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > _MAX_DIRECTORY_ENTRIES:
                    return True
                if entry.name != path.name and _collision_key(entry.name) == wanted:
                    return True
        return False

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise OSError("The duplicate-resolution path is not a regular file.")
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _blocked_from(
        self,
        original: LibraryManagementPlanItem,
        snapshot: LibraryManagementJobSnapshot,
        reason: str,
    ) -> LibraryManagementPlanItem:
        return msgspec.structs.replace(
            original,
            job_id=snapshot.job_id,
            ordinal=0,
            bundle_ordinal=0,
            expected_catalog_revision=snapshot.catalog_revision,
            expected_policy_revision=snapshot.policy_revision,
            expected_profile_revision=snapshot.profile_revision,
            eligibility="stale",
            reason_code=reason,
            created_at=self._clock(),
        )
