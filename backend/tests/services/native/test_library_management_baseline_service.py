import hashlib
import sqlite3

import msgspec
import pytest

from api.v1.schemas.library_management import PICARD_ORGANIZER_PROFILE_ID
from api.v1.schemas.library_policies import LibraryRootSettings
from api.v1.schemas.library_management_preview import (
    LibraryManagementBaselinePurgeRequest,
    LibraryManagementBaselineRestorePreviewRequest,
    LibraryManagementSelectionRequest,
)
from core.exceptions import ValidationError
from infrastructure.audio.metadata_engine import AudioMetadataEngine
from infrastructure.library_management_blob_store import LibraryManagementBlobStore
from models.library_management import (
    BASELINE_UNAVAILABLE,
    PATH_COLLISION_DIFFERENT,
    ROOT_UNAVAILABLE,
)
from models.library_management_planning import LibraryManagementSelection
from services.native.audio_write_planning_service import AudioWritePlanningService
from services.native.library_filesystem_coordinator import LibraryFilesystemCoordinator
from services.native.library_management_baseline_service import (
    LibraryManagementBaselineService,
)
from services.native.library_management_publisher import LibraryManagementPublisher
from services.native.library_management_undo_service import LibraryManagementUndoService
from services.native.library_policy_resolver import LibraryPolicyResolver
from tests.services.native.test_library_management_planner import _configured, _planner
from tests.services.native.test_library_management_publisher import (
    _ready_apply_operation,
    _update_profile,
)


def _semantic_value(value) -> dict:
    encoded = msgspec.to_builtins(value)
    encoded.pop("technical")
    encoded.pop("file_attributes")
    return encoded


def _finish_job(store, job_id: str, now: float) -> None:
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE library_operation_jobs SET state='succeeded',terminal_at=?,"
            "lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?,"
            "row_revision=row_revision+1,event_revision=event_revision+1 WHERE id=?",
            (now, now, job_id),
        )


def _baseline_service(tmp_path, store, preferences, audio, *, now: float):
    filesystem = LibraryFilesystemCoordinator()
    blobs = LibraryManagementBlobStore(tmp_path / "blobs", store)
    undo = LibraryManagementUndoService(
        store,
        preferences,
        audio,
        blobs,
        filesystem,
        clock=lambda: now,
    )
    return LibraryManagementBaselineService(
        store,
        preferences,
        audio,
        blobs,
        filesystem,
        undo,
        clock=lambda: now,
    )


async def _create_and_run_restore_preview(
    service,
    store,
    *,
    settings_revision: str,
    policy_revision: str,
    idempotency_key: str,
):
    preview = await service.create_restore_preview(
        LibraryManagementBaselineRestorePreviewRequest(
            selection=LibraryManagementSelectionRequest(kind="tracks", ids=["track-1"]),
            expected_settings_revision=settings_revision,
            expected_policy_revision=policy_revision,
            idempotency_key=idempotency_key,
        ),
        "admin",
    )
    claimed = await store.claim_operation_job(
        f"{idempotency_key}-worker",
        now=140.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed is not None
    await service.run_claimed_preview(claimed, f"{idempotency_key}-worker")
    return preview


@pytest.mark.asyncio
async def test_baseline_restore_returns_a_to_original_after_a_then_b(tmp_path) -> None:
    (
        root,
        original_path,
        store,
        audio,
        publisher,
        first_job_id,
    ) = await _ready_apply_operation(tmp_path)
    original = audio.snapshot(original_path)
    await publisher.publish_bundle(first_job_id, 0, "apply-worker")
    first = await store.get_target_track("track-1")
    assert first is not None
    first_path = root / str(first["relative_path"])
    _finish_job(store, first_job_id, 115.0)

    def change_naming(settings, profile) -> None:
        script = next(
            value
            for value in settings.naming_scripts
            if value.id == profile.organization.naming_script_id
        )
        script.source = (
            "B/{albumartist}/{album} ({year})/" "{disc:02d}{track:02d} {title}.{ext}"
        )

    _update_profile(publisher._preferences, change_naming)
    management = publisher._preferences.get_library_management_settings()
    policy_revision = LibraryPolicyResolver(
        publisher._preferences.get_typed_library_settings_raw()
    ).policy_revision
    second_planner = _planner(tmp_path, store, publisher._preferences)
    second = await second_planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=management.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="baseline-second-preview",
    )
    second_preview_job = await store.claim_operation_job(
        "baseline-second-preview-worker",
        now=116.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert second_preview_job is not None
    await second_planner.run_claimed_preview(
        second_preview_job, "baseline-second-preview-worker"
    )
    second_ready = await store.get_operation_job(second.job_id)
    assert second_ready is not None
    await store.begin_library_management_apply(
        second.job_id,
        preview_token_hash=hashlib.sha256(second.preview_token.encode()).hexdigest(),
        expected_job_revision=int(second_ready["row_revision"]),
        idempotency_key="baseline-second-apply",
        now=117.0,
    )
    second_apply_job = await store.claim_operation_job(
        "baseline-second-apply-worker",
        now=118.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert second_apply_job is not None
    second_work = await store.claim_operation_work(
        second.job_id, "baseline-second-apply-worker", now=119.0
    )
    assert second_work is not None
    await publisher.publish_bundle(
        second.job_id,
        int(second_work["ordinal"]),
        "baseline-second-apply-worker",
    )
    second_track = await store.get_target_track("track-1")
    assert second_track is not None
    second_path = root / str(second_track["relative_path"])
    assert second_path.is_file() and second_path != first_path
    _finish_job(store, second.job_id, 120.0)

    filesystem = LibraryFilesystemCoordinator()
    blobs = LibraryManagementBlobStore(tmp_path / "blobs", store)
    undo = LibraryManagementUndoService(
        store,
        publisher._preferences,
        audio,
        blobs,
        filesystem,
        clock=lambda: 125.0,
    )
    baseline_service = LibraryManagementBaselineService(
        store,
        publisher._preferences,
        audio,
        blobs,
        filesystem,
        undo,
        clock=lambda: 125.0,
    )
    restore = await baseline_service.create_restore_preview(
        LibraryManagementBaselineRestorePreviewRequest(
            selection=LibraryManagementSelectionRequest(kind="tracks", ids=["track-1"]),
            expected_settings_revision=management.settings_revision,
            expected_policy_revision=policy_revision,
            idempotency_key="baseline-restore-preview",
        ),
        "admin",
    )
    restore_preview_job = await store.claim_operation_job(
        "baseline-restore-preview-worker",
        now=126.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert restore_preview_job is not None
    await baseline_service.run_claimed_preview(
        restore_preview_job, "baseline-restore-preview-worker"
    )
    items = await store.list_library_management_plan_items(restore.job_id)
    assert len(items) == 1 and items[0].eligibility == "eligible"
    assert items[0].destination_relative_path == "source.flac"
    restore_ready = await store.get_operation_job(restore.job_id)
    assert restore_ready is not None
    await store.begin_library_management_apply(
        restore.job_id,
        preview_token_hash=hashlib.sha256(restore.preview_token.encode()).hexdigest(),
        expected_job_revision=int(restore_ready["row_revision"]),
        idempotency_key="baseline-restore-apply",
        now=127.0,
    )
    restore_apply_job = await store.claim_operation_job(
        "baseline-restore-apply-worker",
        now=128.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert restore_apply_job is not None
    restore_work = await store.claim_operation_work(
        restore.job_id, "baseline-restore-apply-worker", now=129.0
    )
    assert restore_work is not None
    restore_audio = AudioMetadataEngine()
    restore_publisher = LibraryManagementPublisher(
        store,
        publisher._preferences,
        restore_audio,
        AudioWritePlanningService(restore_audio),
        blobs,
        filesystem,
        clock=lambda: 130.0,
    )

    await restore_publisher.publish_bundle(
        restore.job_id,
        int(restore_work["ordinal"]),
        "baseline-restore-apply-worker",
    )

    restored = await store.get_target_track("track-1")
    baseline = await store.get_management_baseline("track-1")
    state = await store.get_track_management_state("track-1")
    assert restored is not None and restored["relative_path"] == "source.flac"
    assert original_path.is_file()
    assert second_path.exists() is False
    assert _semantic_value(audio.snapshot(original_path)) == _semantic_value(original)
    assert baseline is not None and baseline.restore_status == "restored"
    assert state is not None
    assert state.baseline_id == baseline.id
    assert state.applied_profile_id is None
    assert state.last_outcome == "restored"


@pytest.mark.asyncio
async def test_baseline_purge_requires_impact_typed_confirmation_and_is_idempotent(
    tmp_path,
) -> None:
    _root, _source, store, audio, publisher, job_id = await _ready_apply_operation(
        tmp_path
    )
    await publisher.publish_bundle(job_id, 0, "apply-worker")
    filesystem = LibraryFilesystemCoordinator()
    blobs = LibraryManagementBlobStore(tmp_path / "blobs", store)
    undo = LibraryManagementUndoService(
        store,
        publisher._preferences,
        audio,
        blobs,
        filesystem,
    )
    service = LibraryManagementBaselineService(
        store,
        publisher._preferences,
        audio,
        blobs,
        filesystem,
        undo,
        clock=lambda: 130.0,
    )
    impact = await service.purge_impact()
    assert impact.baseline_count == 1
    assert impact.referenced_blob_count >= 1

    with pytest.raises(ValidationError, match="PURGE BASELINES"):
        await service.purge(
            LibraryManagementBaselinePurgeRequest(
                impact_token=impact.impact_token,
                expected_catalog_revision=impact.catalog_revision,
                typed_confirmation="purge baselines",
                idempotency_key="purge-baselines-once",
            ),
            "admin",
        )

    request = LibraryManagementBaselinePurgeRequest(
        impact_token=impact.impact_token,
        expected_catalog_revision=impact.catalog_revision,
        typed_confirmation="PURGE BASELINES",
        idempotency_key="purge-baselines-once",
    )
    purged = await service.purge(request, "admin")
    repeated = await service.purge(request, "admin")

    state = await store.get_track_management_state("track-1")
    assert purged.purged_baseline_count == 1
    assert repeated.purged_baseline_count == 1
    assert repeated.existing is True
    assert await store.get_management_baseline("track-1") is None
    assert state is not None and state.baseline_id is None
    with sqlite3.connect(store.db_path) as connection:
        baseline_references = connection.execute(
            "SELECT COUNT(*) FROM library_management_blob_references "
            "WHERE reference_kind='baseline'"
        ).fetchone()[0]
    assert baseline_references == 0


@pytest.mark.asyncio
async def test_baseline_restore_preview_blocks_track_without_baseline(tmp_path) -> None:
    _root, _source, preferences, store, settings_revision, policy_revision = (
        _configured(tmp_path)
    )
    service = _baseline_service(
        tmp_path, store, preferences, AudioMetadataEngine(), now=130.0
    )

    preview = await _create_and_run_restore_preview(
        service,
        store,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        idempotency_key="missing-baseline-preview",
    )

    items = await store.list_library_management_plan_items(preview.job_id)
    assert len(items) == 1
    assert items[0].eligibility == "blocked"
    assert items[0].reason_code == BASELINE_UNAVAILABLE


@pytest.mark.asyncio
async def test_baseline_restore_preview_blocks_removed_original_root(tmp_path) -> None:
    _root, _source, store, audio, publisher, job_id = await _ready_apply_operation(
        tmp_path
    )
    await publisher.publish_bundle(job_id, 0, "apply-worker")
    _finish_job(store, job_id, 115.0)
    replacement = tmp_path / "replacement-root"
    replacement.mkdir()
    library = publisher._preferences.get_typed_library_settings_raw()
    library.library_roots = [
        LibraryRootSettings(
            id="root-2",
            path=str(replacement),
            label="Replacement",
            policy="automatic",
            rules=[],
        )
    ]
    publisher._preferences.save_typed_library_settings(library)
    settings_revision = (
        publisher._preferences.get_library_management_settings().settings_revision
    )
    policy_revision = LibraryPolicyResolver(
        publisher._preferences.get_typed_library_settings_raw()
    ).policy_revision
    service = _baseline_service(
        tmp_path, store, publisher._preferences, audio, now=130.0
    )

    preview = await _create_and_run_restore_preview(
        service,
        store,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        idempotency_key="removed-root-preview",
    )

    items = await store.list_library_management_plan_items(preview.job_id)
    assert len(items) == 1
    assert items[0].eligibility == "blocked"
    assert items[0].reason_code == ROOT_UNAVAILABLE


@pytest.mark.asyncio
async def test_baseline_restore_preview_blocks_occupied_original_path(tmp_path) -> None:
    root, original_path, store, audio, publisher, job_id = await _ready_apply_operation(
        tmp_path
    )
    await publisher.publish_bundle(job_id, 0, "apply-worker")
    _finish_job(store, job_id, 115.0)
    original_path.write_bytes(b"third-party replacement")
    settings_revision = (
        publisher._preferences.get_library_management_settings().settings_revision
    )
    policy_revision = LibraryPolicyResolver(
        publisher._preferences.get_typed_library_settings_raw()
    ).policy_revision
    service = _baseline_service(
        tmp_path, store, publisher._preferences, audio, now=130.0
    )

    preview = await _create_and_run_restore_preview(
        service,
        store,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        idempotency_key="occupied-baseline-path-preview",
    )

    items = await store.list_library_management_plan_items(preview.job_id)
    assert len(items) == 1
    assert items[0].eligibility == "blocked"
    assert items[0].reason_code == PATH_COLLISION_DIFFERENT
    assert original_path.read_bytes() == b"third-party replacement"
    assert root.is_dir()
