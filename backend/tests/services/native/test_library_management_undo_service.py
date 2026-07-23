import hashlib
import sqlite3

import msgspec
import pytest

from api.v1.schemas.library_management import PICARD_ORGANIZER_PROFILE_ID
from api.v1.schemas.library_management_preview import (
    LibraryManagementUndoPreviewRequest,
)
from infrastructure.audio.metadata_engine import AudioMetadataEngine
from infrastructure.library_management_blob_store import LibraryManagementBlobStore
from services.native.audio_write_planning_service import AudioWritePlanningService
from services.native.library_filesystem_coordinator import LibraryFilesystemCoordinator
from services.native.library_management_publisher import LibraryManagementPublisher
from services.native.library_management_undo_service import LibraryManagementUndoService
from services.native.library_policy_resolver import LibraryPolicyResolver
from models.library_management_planning import LibraryManagementSelection
from models.library_management import UNDO_EXPIRED
from tests.services.native.test_library_management_publisher import (
    _external_artwork_configuration,
    _ready_apply_operation,
    _sidecar_configuration,
    _update_profile,
)
from tests.services.native.test_library_management_planner import (
    _ArtworkRepository,
    _planner,
)


def _semantic_value(value) -> dict:
    encoded = msgspec.to_builtins(value)
    encoded.pop("technical")
    encoded.pop("file_attributes")
    return encoded


@pytest.mark.asyncio
async def test_undo_restores_real_audio_path_tags_and_management_state(
    tmp_path,
) -> None:
    (
        root,
        source,
        store,
        audio,
        first_publisher,
        source_job_id,
    ) = await _ready_apply_operation(tmp_path)
    first_job_id = source_job_id
    await first_publisher.publish_bundle(source_job_id, 0, "apply-worker")
    first_managed = await store.get_target_track("track-1")
    assert first_managed is not None
    first_path = root / str(first_managed["relative_path"])
    first_relative_path = str(first_managed["relative_path"])
    first_snapshot = audio.snapshot(first_path)
    assert first_path != source
    assert first_path.is_file()

    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE library_operation_jobs SET state='succeeded',terminal_at=115,"
            "lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=115,"
            "row_revision=row_revision+1,event_revision=event_revision+1 WHERE id=?",
            (source_job_id,),
        )

    def change_naming(settings, profile) -> None:
        script = next(
            value
            for value in settings.naming_scripts
            if value.id == profile.organization.naming_script_id
        )
        script.source = (
            "B/{albumartist}/{album} ({year})/" "{disc:02d}{track:02d} {title}.{ext}"
        )

    _update_profile(first_publisher._preferences, change_naming)
    current = first_publisher._preferences.get_library_management_settings()
    policy_revision = LibraryPolicyResolver(
        first_publisher._preferences.get_typed_library_settings_raw()
    ).policy_revision
    second_planner = _planner(tmp_path, store, first_publisher._preferences)
    second = await second_planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=current.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="second-management-preview",
    )
    claimed_second_preview = await store.claim_operation_job(
        "second-preview-worker",
        now=116.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed_second_preview is not None
    await second_planner.run_claimed_preview(
        claimed_second_preview, "second-preview-worker"
    )
    second_ready = await store.get_operation_job(second.job_id)
    assert second_ready is not None and second_ready["state"] == "ready"
    await store.begin_library_management_apply(
        second.job_id,
        preview_token_hash=hashlib.sha256(second.preview_token.encode()).hexdigest(),
        expected_job_revision=int(second_ready["row_revision"]),
        idempotency_key="second-management-apply",
        now=117.0,
    )
    claimed_second_apply = await store.claim_operation_job(
        "second-apply-worker",
        now=118.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed_second_apply is not None
    second_work = await store.claim_operation_work(
        second.job_id, "second-apply-worker", now=119.0
    )
    assert second_work is not None
    await first_publisher.publish_bundle(
        second.job_id, int(second_work["ordinal"]), "second-apply-worker"
    )
    second_managed = await store.get_target_track("track-1")
    assert second_managed is not None
    second_path = root / str(second_managed["relative_path"])
    assert second_path != first_path
    assert second_path.is_file()
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE library_operation_jobs SET state='succeeded',terminal_at=120,"
            "lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=120,"
            "row_revision=row_revision+1,event_revision=event_revision+1 WHERE id=?",
            (second.job_id,),
        )
    source_job_id = second.job_id
    source_job = await store.get_operation_job(source_job_id)
    assert source_job is not None

    filesystem = LibraryFilesystemCoordinator()
    blobs = LibraryManagementBlobStore(tmp_path / "blobs", store)
    undo = LibraryManagementUndoService(
        store,
        first_publisher._preferences,
        audio,
        blobs,
        filesystem,
        clock=lambda: 120.0,
    )
    preview = await undo.create_preview(
        source_job_id,
        LibraryManagementUndoPreviewRequest(
            expected_operation_row_revision=int(source_job["row_revision"]),
            idempotency_key="undo-preview-1",
        ),
        "admin",
    )
    claimed_preview = await store.claim_operation_job(
        "undo-preview-worker",
        now=121.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed_preview is not None
    assert claimed_preview["id"] == preview.job_id
    await undo.run_claimed_preview(claimed_preview, "undo-preview-worker")

    ready = await store.get_operation_job(preview.job_id)
    assert ready is not None and ready["state"] == "ready"
    await store.begin_library_management_apply(
        preview.job_id,
        preview_token_hash=hashlib.sha256(preview.preview_token.encode()).hexdigest(),
        expected_job_revision=int(ready["row_revision"]),
        idempotency_key="undo-apply-1",
        now=122.0,
    )
    claimed_apply = await store.claim_operation_job(
        "undo-apply-worker",
        now=123.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed_apply is not None and claimed_apply["id"] == preview.job_id
    work = await store.claim_operation_work(
        preview.job_id, "undo-apply-worker", now=124.0
    )
    assert work is not None
    undo_publisher = LibraryManagementPublisher(
        store,
        first_publisher._preferences,
        AudioMetadataEngine(),
        AudioWritePlanningService(AudioMetadataEngine()),
        blobs,
        filesystem,
        clock=lambda: 125.0,
    )

    await undo_publisher.publish_bundle(
        preview.job_id, int(work["ordinal"]), "undo-apply-worker"
    )

    restored = await store.get_target_track("track-1")
    state = await store.get_track_management_state("track-1")
    assert restored is not None
    assert restored["root_id"] == "root-1"
    assert restored["relative_path"] == first_relative_path
    assert first_path.is_file()
    assert second_path.exists() is False
    assert _semantic_value(audio.snapshot(first_path)) == _semantic_value(
        first_snapshot
    )
    assert first_path.stat().st_mtime_ns == first_snapshot.file_attributes.mtime_ns
    assert state is not None
    assert state.applied_profile_id is not None
    assert state.last_operation_job_id == first_job_id
    assert state.last_outcome == "succeeded"
    journals = await store.list_file_mutation_journals_for_bundle(
        preview.job_id, int(work["ordinal"])
    )
    assert journals and all(value.state == "completed" for value in journals)
    assert not list(root.rglob(".droppedneedle-management-*"))


@pytest.mark.asyncio
async def test_undo_restores_sidecar_and_removes_generated_external_artwork(
    tmp_path,
) -> None:
    artwork = _ArtworkRepository()

    def configure(root, preferences, store) -> None:
        _sidecar_configuration(root, preferences, store)
        _external_artwork_configuration(root, preferences, store)

    (
        root,
        source,
        store,
        audio,
        first_publisher,
        source_job_id,
    ) = await _ready_apply_operation(
        tmp_path,
        configure=configure,
        artwork_repository=artwork,
    )
    original_snapshot = audio.snapshot(source)
    original_sidecar = root / "disc.cue"
    original_sidecar_bytes = original_sidecar.read_bytes()

    await first_publisher.publish_bundle(source_job_id, 0, "apply-worker")
    first_journals = await store.list_file_mutation_journals_for_bundle(
        source_job_id, 0
    )
    art_journal = next(
        value for value in first_journals if value.subject_kind == "external_art"
    )
    sidecar_journal = next(
        value for value in first_journals if value.subject_kind == "sidecar"
    )
    generated_art = root / str(art_journal.destination_relative_path)
    moved_sidecar = root / str(sidecar_journal.destination_relative_path)
    assert generated_art.read_bytes() == artwork.content
    assert moved_sidecar.read_bytes() == original_sidecar_bytes
    assert original_sidecar.exists() is False

    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE library_operation_jobs SET state='succeeded',terminal_at=115,"
            "lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=115,"
            "row_revision=row_revision+1,event_revision=event_revision+1 WHERE id=?",
            (source_job_id,),
        )
    source_job = await store.get_operation_job(source_job_id)
    assert source_job is not None
    filesystem = LibraryFilesystemCoordinator()
    blobs = LibraryManagementBlobStore(tmp_path / "blobs", store)
    undo = LibraryManagementUndoService(
        store,
        first_publisher._preferences,
        audio,
        blobs,
        filesystem,
        clock=lambda: 120.0,
    )
    preview = await undo.create_preview(
        source_job_id,
        LibraryManagementUndoPreviewRequest(
            expected_operation_row_revision=int(source_job["row_revision"]),
            idempotency_key="undo-ancillary-preview",
        ),
        "admin",
    )
    claimed_preview = await store.claim_operation_job(
        "undo-ancillary-preview-worker",
        now=121.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed_preview is not None
    await undo.run_claimed_preview(claimed_preview, "undo-ancillary-preview-worker")
    ready = await store.get_operation_job(preview.job_id)
    assert ready is not None and ready["state"] == "ready"
    await store.begin_library_management_apply(
        preview.job_id,
        preview_token_hash=hashlib.sha256(preview.preview_token.encode()).hexdigest(),
        expected_job_revision=int(ready["row_revision"]),
        idempotency_key="undo-ancillary-apply",
        now=122.0,
    )
    claimed_apply = await store.claim_operation_job(
        "undo-ancillary-apply-worker",
        now=123.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed_apply is not None
    work = await store.claim_operation_work(
        preview.job_id, "undo-ancillary-apply-worker", now=124.0
    )
    assert work is not None
    undo_publisher = LibraryManagementPublisher(
        store,
        first_publisher._preferences,
        audio,
        AudioWritePlanningService(audio),
        blobs,
        filesystem,
        clock=lambda: 125.0,
    )

    await undo_publisher.publish_bundle(
        preview.job_id,
        int(work["ordinal"]),
        "undo-ancillary-apply-worker",
    )

    restored = await store.get_target_track("track-1")
    undo_journals = await store.list_file_mutation_journals_for_bundle(
        preview.job_id, int(work["ordinal"])
    )
    assert restored is not None and restored["relative_path"] == "source.flac"
    assert _semantic_value(audio.snapshot(source)) == _semantic_value(original_snapshot)
    assert original_sidecar.read_bytes() == original_sidecar_bytes
    assert moved_sidecar.exists() is False
    assert generated_art.exists() is False
    assert any(value.subject_key.startswith("delete:") for value in undo_journals)
    assert all(value.state == "completed" for value in undo_journals)
    assert not list(root.rglob(".droppedneedle-management-*"))


@pytest.mark.asyncio
async def test_undo_preview_marks_expired_snapshot_stale(tmp_path) -> None:
    (
        _root,
        _source,
        store,
        audio,
        publisher,
        source_job_id,
    ) = await _ready_apply_operation(tmp_path)
    await publisher.publish_bundle(source_job_id, 0, "apply-worker")
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE library_operation_jobs SET state='succeeded',terminal_at=115,"
            "lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=115,"
            "row_revision=row_revision+1,event_revision=event_revision+1 WHERE id=?",
            (source_job_id,),
        )
        connection.execute(
            "UPDATE library_management_operation_snapshots SET expires_at=119 "
            "WHERE job_id=?",
            (source_job_id,),
        )
    source_job = await store.get_operation_job(source_job_id)
    assert source_job is not None
    undo = LibraryManagementUndoService(
        store,
        publisher._preferences,
        audio,
        LibraryManagementBlobStore(tmp_path / "blobs", store),
        LibraryFilesystemCoordinator(),
        clock=lambda: 120.0,
    )
    preview = await undo.create_preview(
        source_job_id,
        LibraryManagementUndoPreviewRequest(
            expected_operation_row_revision=int(source_job["row_revision"]),
            idempotency_key="expired-undo-preview",
        ),
        "admin",
    )
    claimed = await store.claim_operation_job(
        "expired-undo-worker",
        now=120.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed is not None
    await undo.run_claimed_preview(claimed, "expired-undo-worker")

    items = await store.list_library_management_plan_items(preview.job_id)
    snapshot = await store.get_library_management_job_snapshot(preview.job_id)
    assert len(items) == 1
    assert items[0].eligibility == "stale"
    assert items[0].reason_code == UNDO_EXPIRED
    assert snapshot is not None
    assert snapshot.summary_json.find('"stale_count":1') >= 0
