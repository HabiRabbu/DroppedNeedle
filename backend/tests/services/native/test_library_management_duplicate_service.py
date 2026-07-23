import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from api.v1.schemas.library_management import PICARD_ORGANIZER_PROFILE_ID
from api.v1.schemas.library_management_preview import (
    LibraryManagementDuplicateResolutionPreviewRequest,
    LibraryManagementUndoPreviewRequest,
)
from core.exceptions import StaleRevisionError
from infrastructure.audio.metadata_engine import AudioMetadataEngine
from infrastructure.library_management_blob_store import LibraryManagementBlobStore
from models.library_management import (
    MANAGEMENT_RECYCLE_ROOT_ID,
    RECYCLE_UNAVAILABLE,
    SIDECAR_COLLISION,
)
from models.library_management_planning import LibraryManagementSelection
from services.native.audio_write_planning_service import AudioWritePlanningService
from services.native.library_filesystem_coordinator import LibraryFilesystemCoordinator
from services.native.library_management_duplicate_service import (
    LibraryManagementDuplicateService,
)
from services.native.library_management_publisher import LibraryManagementPublisher
from services.native.library_management_recovery_service import (
    LibraryManagementRecoveryService,
)
from services.native.library_management_undo_service import LibraryManagementUndoService
from services.native.library_policy_resolver import LibraryPolicyResolver
from tests.services.native.test_library_management_planner import _configured, _planner
from tests.services.native.test_library_management_publisher import (
    _add_second_album_track,
)


def _configure_collision(
    preferences,
    recycle: Path | None,
    *,
    destination_relative: str = "organized/collision.flac",
    move_sidecars: bool = False,
) -> tuple[str, str]:
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    script = next(
        value
        for value in settings.naming_scripts
        if value.id == profile.organization.naming_script_id
    )
    script.source = destination_relative.replace(".flac", ".{ext}")
    profile.organization.move_sidecars = move_sidecars
    settings.recycle_bin_path = str(recycle) if recycle is not None else ""
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    policy_revision = LibraryPolicyResolver(
        preferences.get_typed_library_settings_raw()
    ).policy_revision
    return saved.settings_revision, policy_revision


async def _collision_preview(
    tmp_path: Path,
    *,
    recycle_available: bool = True,
    identical: bool = True,
    destination_relative: str = "organized/collision.flac",
    existing_relative: str | None = None,
    sidecar_collision: bool = False,
):
    root, source, preferences, store, _settings, _policy = _configured(tmp_path)
    recycle = tmp_path / "recycle"
    if recycle_available:
        recycle.mkdir()
    settings_revision, policy_revision = _configure_collision(
        preferences,
        recycle if recycle_available else None,
        destination_relative=destination_relative,
        move_sidecars=sidecar_collision,
    )
    existing_relative = existing_relative or destination_relative
    occupied = root / existing_relative
    occupied.parent.mkdir()
    if sidecar_collision:
        (root / "disc.cue").write_text("FILE source.flac", encoding="utf-8")
        occupied.write_text("FILE existing.flac", encoding="utf-8")
    else:
        shutil.copy2(source, occupied)
        if not identical:
            occupied.write_bytes(occupied.read_bytes() + b"different")
    planner = _planner(tmp_path, store, preferences)
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="collision-source-preview",
    )
    claimed = await store.claim_operation_job(
        "source-worker", now=100.0, lease_seconds=60.0, kind="library_management"
    )
    assert claimed is not None
    await planner.run_claimed_preview(claimed, "source-worker")
    source_job = await store.get_operation_job(handle.job_id)
    assert source_job is not None
    filesystem = LibraryFilesystemCoordinator()
    service = LibraryManagementDuplicateService(
        store, preferences, filesystem, clock=lambda: 110.0
    )
    return (
        root,
        source,
        occupied,
        recycle,
        preferences,
        store,
        planner,
        service,
        handle.job_id,
        int(source_job["row_revision"]),
        settings_revision,
        policy_revision,
        filesystem,
    )


async def _create_resolution(
    service,
    store,
    *,
    source_job_id: str,
    source_revision: int,
    settings_revision: str,
    policy_revision: str,
    action: str,
    collision_kind: str = "same_path_same_content",
    existing_relative_path: str = "organized/collision.flac",
    existing_local_track_id: str | None = None,
    alternate_relative_path: str | None = None,
    key: str = "duplicate-resolution",
):
    handle = await service.create_preview(
        LibraryManagementDuplicateResolutionPreviewRequest(
            source_job_id=source_job_id,
            source_plan_item_ordinal=0,
            expected_source_operation_row_revision=source_revision,
            collision_kind=collision_kind,
            existing_root_id="root-1",
            existing_relative_path=existing_relative_path,
            existing_local_track_id=existing_local_track_id,
            action=action,
            alternate_relative_path=alternate_relative_path,
            expected_settings_revision=settings_revision,
            expected_policy_revision=policy_revision,
            idempotency_key=key,
        ),
        "admin",
    )
    claimed = await store.claim_operation_job(
        f"{key}-planner", now=111.0, lease_seconds=60.0, kind="library_management"
    )
    assert claimed is not None
    await service.run_claimed_preview(claimed, f"{key}-planner")
    return handle


async def _begin_and_publish(
    tmp_path: Path,
    handle,
    store,
    preferences,
    planner,
    filesystem,
):
    publisher, work = await _begin_apply(
        tmp_path, handle, store, preferences, planner, filesystem
    )
    await publisher.publish_bundle(
        handle.job_id, int(work["ordinal"]), "duplicate-apply-worker"
    )
    return publisher


async def _begin_apply(
    tmp_path: Path,
    handle,
    store,
    preferences,
    planner,
    filesystem,
):
    del planner
    ready = await store.get_operation_job(handle.job_id)
    assert ready is not None
    await store.begin_library_management_apply(
        handle.job_id,
        preview_token_hash=hashlib.sha256(handle.preview_token.encode()).hexdigest(),
        expected_job_revision=int(ready["row_revision"]),
        idempotency_key=f"apply-{handle.job_id}",
        now=112.0,
    )
    claimed = await store.claim_operation_job(
        "duplicate-apply-worker",
        now=113.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed is not None
    work = await store.claim_operation_work(
        handle.job_id, "duplicate-apply-worker", now=114.0
    )
    assert work is not None
    audio = AudioMetadataEngine()
    publisher = LibraryManagementPublisher(
        store,
        preferences,
        audio,
        AudioWritePlanningService(audio),
        LibraryManagementBlobStore(tmp_path / "blobs", store),
        filesystem,
        clock=lambda: 115.0,
    )
    return publisher, work


@pytest.mark.asyncio
async def test_keep_existing_is_explicit_no_write_preview(tmp_path: Path) -> None:
    (
        _root,
        source,
        occupied,
        _recycle,
        _preferences,
        store,
        _planner_value,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        _filesystem,
    ) = await _collision_preview(tmp_path)
    source_before = source.read_bytes()
    occupied_before = occupied.read_bytes()

    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="keep_existing",
    )
    items = await store.list_library_management_plan_items(handle.job_id)

    assert len(items) == 1
    assert items[0].eligibility == "eligible"
    assert json.loads(items[0].diff_json)["requires_write"] is False
    assert source.read_bytes() == source_before
    assert occupied.read_bytes() == occupied_before
    assert await store.list_file_mutation_journals_for_bundle(handle.job_id, 0) == []


@pytest.mark.asyncio
async def test_keep_incoming_under_explicit_alternate_path(tmp_path: Path) -> None:
    (
        root,
        source,
        occupied,
        _recycle,
        preferences,
        store,
        planner,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        filesystem,
    ) = await _collision_preview(tmp_path, identical=False)
    occupied_before = occupied.read_bytes()
    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="keep_incoming_alternate",
        collision_kind="same_path_different_content",
        alternate_relative_path="organized/collision-incoming.flac",
    )

    await _begin_and_publish(tmp_path, handle, store, preferences, planner, filesystem)

    assert source.exists() is False
    assert occupied.read_bytes() == occupied_before
    assert (root / "organized" / "collision-incoming.flac").is_file()
    track = await store.get_target_track("track-1")
    assert track is not None
    assert track["relative_path"] == "organized/collision-incoming.flac"


@pytest.mark.asyncio
async def test_exact_content_label_cannot_be_used_after_bytes_differ(
    tmp_path: Path,
) -> None:
    (
        _root,
        _source,
        _occupied,
        _recycle,
        _preferences,
        store,
        _planner_value,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        _filesystem,
    ) = await _collision_preview(tmp_path, identical=False)

    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="keep_existing",
        collision_kind="same_path_same_content",
        key="incorrect-exact-label",
    )
    item = (await store.list_library_management_plan_items(handle.job_id))[0]

    assert item.eligibility == "stale"


@pytest.mark.asyncio
async def test_recycle_incoming_preserves_existing_and_catalog_identity(
    tmp_path: Path,
) -> None:
    (
        _root,
        source,
        occupied,
        recycle,
        preferences,
        store,
        planner,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        filesystem,
    ) = await _collision_preview(tmp_path)
    occupied_before = occupied.read_bytes()
    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="recycle_incoming_keep_existing",
    )

    await _begin_and_publish(tmp_path, handle, store, preferences, planner, filesystem)

    track = await store.get_target_track("track-1")
    snapshots = await store.list_management_operation_snapshots(handle.job_id)
    journals = await store.list_file_mutation_journals_for_bundle(handle.job_id, 0)
    assert source.exists() is False
    assert occupied.read_bytes() == occupied_before
    assert track is not None
    assert track["root_id"] == MANAGEMENT_RECYCLE_ROOT_ID
    assert track["availability"] == "missing"
    assert Path(str(track["file_path"])).is_file()
    assert recycle in Path(str(track["file_path"])).parents
    assert len(snapshots) == 1
    assert [value.state for value in journals] == ["completed"]


@pytest.mark.asyncio
async def test_recycle_untracked_existing_then_publish_incoming(tmp_path: Path) -> None:
    (
        _root,
        source,
        occupied,
        recycle,
        preferences,
        store,
        planner,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        filesystem,
    ) = await _collision_preview(tmp_path, identical=False)
    old_bytes = occupied.read_bytes()
    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="recycle_existing_keep_incoming",
        collision_kind="same_path_different_content",
    )

    await _begin_and_publish(tmp_path, handle, store, preferences, planner, filesystem)

    track = await store.get_target_track("track-1")
    recycled = list(recycle.rglob("*collision.flac"))
    assert source.exists() is False
    assert occupied.is_file()
    assert occupied.read_bytes() != old_bytes
    assert len(recycled) == 1 and recycled[0].read_bytes() == old_bytes
    assert track is not None and track["relative_path"] == "organized/collision.flac"


@pytest.mark.asyncio
async def test_recycle_action_blocks_when_recycle_bin_is_not_configured(
    tmp_path: Path,
) -> None:
    (
        _root,
        _source,
        _occupied,
        _recycle,
        _preferences,
        store,
        _planner_value,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        _filesystem,
    ) = await _collision_preview(tmp_path, recycle_available=False)
    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="recycle_incoming_keep_existing",
    )
    items = await store.list_library_management_plan_items(handle.job_id)

    assert items[0].eligibility == "blocked"
    assert items[0].reason_code == RECYCLE_UNAVAILABLE


@pytest.mark.parametrize(
    ("destination_relative", "existing_relative"),
    [
        ("organized/collision.flac", "organized/Collision.flac"),
        (
            "organized/Caf\N{LATIN SMALL LETTER E WITH ACUTE}.flac",
            "organized/Cafe\N{COMBINING ACUTE ACCENT}.flac",
        ),
    ],
    ids=("case", "unicode-normalization"),
)
@pytest.mark.asyncio
async def test_normalized_collision_requires_the_exact_matching_sibling(
    tmp_path: Path,
    destination_relative: str,
    existing_relative: str,
) -> None:
    (
        _root,
        _source,
        _occupied,
        _recycle,
        _preferences,
        store,
        _planner_value,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        _filesystem,
    ) = await _collision_preview(
        tmp_path,
        destination_relative=destination_relative,
        existing_relative=existing_relative,
    )

    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="keep_existing",
        collision_kind="normalized_path_collision",
        existing_relative_path=existing_relative,
        key=f"normalized-{destination_relative}",
    )
    item = (await store.list_library_management_plan_items(handle.job_id))[0]

    assert item.eligibility == "eligible"
    evidence = json.loads(item.collision_json)[0]
    assert evidence["existing_relative_path"] == existing_relative
    assert evidence["exact_content"] is True


@pytest.mark.asyncio
async def test_sidecar_collision_can_replan_the_complete_sidecar_at_alternate_path(
    tmp_path: Path,
) -> None:
    (
        root,
        source,
        occupied,
        _recycle,
        preferences,
        store,
        planner,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        filesystem,
    ) = await _collision_preview(
        tmp_path,
        existing_relative="organized/disc.cue",
        sidecar_collision=True,
    )
    source_item = (await store.list_library_management_plan_items(source_job_id))[0]
    assert source_item.reason_code == SIDECAR_COLLISION
    planned_sidecars = json.loads(source_item.diff_json)["sidecars"]
    assert planned_sidecars[0]["destination_collision"] is True
    occupied_before = occupied.read_bytes()

    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="keep_incoming_alternate",
        collision_kind="sidecar_collision",
        existing_relative_path="organized/disc.cue",
        alternate_relative_path="alternate/collision.flac",
        key="sidecar-alternate",
    )
    item = (await store.list_library_management_plan_items(handle.job_id))[0]
    assert item.eligibility == "eligible"

    await _begin_and_publish(tmp_path, handle, store, preferences, planner, filesystem)

    assert source.exists() is False
    assert occupied.read_bytes() == occupied_before
    assert (root / "alternate" / "collision.flac").is_file()
    assert (root / "alternate" / "disc.cue").read_text(encoding="utf-8") == (
        "FILE source.flac"
    )


@pytest.mark.asyncio
async def test_same_release_position_collision_requires_matching_track_identity(
    tmp_path: Path,
) -> None:
    root, _source, preferences, store, _settings, _policy = _configured(tmp_path)
    recycle = tmp_path / "recycle"
    recycle.mkdir()
    _add_second_album_track(root, preferences, store)
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.organization.rename_enabled = False
    profile.organization.move_enabled = False
    profile.organization.move_sidecars = False
    settings.recycle_bin_path = str(recycle)
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE local_track_external_identities SET release_track_mbid="
            "'22222222-2222-4222-8222-222222222222',"
            "release_track_position=1 WHERE local_track_id='track-2'"
        )
    existing = root / "source2.flac"
    existing.write_bytes(existing.read_bytes() + b"position-collision")
    policy_revision = LibraryPolicyResolver(
        preferences.get_typed_library_settings_raw()
    ).policy_revision
    planner = _planner(tmp_path, store, preferences)
    source = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="position-source",
    )
    claimed = await store.claim_operation_job(
        "position-source-worker",
        now=100.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed is not None
    await planner.run_claimed_preview(claimed, "position-source-worker")
    source_job = await store.get_operation_job(source.job_id)
    assert source_job is not None
    service = LibraryManagementDuplicateService(
        store, preferences, LibraryFilesystemCoordinator(), clock=lambda: 110.0
    )

    handle = await _create_resolution(
        service,
        store,
        source_job_id=source.job_id,
        source_revision=int(source_job["row_revision"]),
        settings_revision=saved.settings_revision,
        policy_revision=policy_revision,
        action="keep_existing",
        collision_kind="same_release_position_different_content",
        existing_relative_path="source2.flac",
        existing_local_track_id="track-2",
        key="position-resolution",
    )
    item = (await store.list_library_management_plan_items(handle.job_id))[0]

    assert item.eligibility == "eligible"
    assert json.loads(item.collision_json)[0]["exact_content"] is False


@pytest.mark.parametrize("changed_side", ["source", "existing"])
@pytest.mark.asyncio
async def test_resolution_publish_rejects_either_file_changing_after_fresh_preview(
    tmp_path: Path,
    changed_side: str,
) -> None:
    (
        _root,
        source,
        occupied,
        recycle,
        preferences,
        store,
        planner,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        filesystem,
    ) = await _collision_preview(tmp_path, identical=False)
    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="recycle_existing_keep_incoming",
        collision_kind="same_path_different_content",
        key=f"changed-{changed_side}",
    )
    changed = source if changed_side == "source" else occupied
    changed.write_bytes(changed.read_bytes() + b"changed-after-resolution-preview")
    changed_bytes = changed.read_bytes()
    publisher, work = await _begin_apply(
        tmp_path, handle, store, preferences, planner, filesystem
    )

    with pytest.raises(StaleRevisionError):
        await publisher.publish_bundle(
            handle.job_id, int(work["ordinal"]), "duplicate-apply-worker"
        )

    assert changed.read_bytes() == changed_bytes
    assert not [value for value in recycle.rglob("*") if value.is_file()]


@pytest.mark.asyncio
async def test_recovery_finishes_recycle_after_source_backup_journal_fault(
    tmp_path: Path,
) -> None:
    (
        _root,
        source,
        _occupied,
        recycle,
        preferences,
        store,
        planner,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        filesystem,
    ) = await _collision_preview(tmp_path)
    original_bytes = source.read_bytes()
    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="recycle_incoming_keep_existing",
        key="recycle-recovery",
    )
    publisher, work = await _begin_apply(
        tmp_path, handle, store, preferences, planner, filesystem
    )
    snapshot = await store.get_library_management_job_snapshot(handle.job_id)
    assert snapshot is not None
    pinned, roots = publisher.recovery_configuration(snapshot)
    item = (await store.get_library_management_bundle_plan_items(handle.job_id, 0))[0]
    prepared = await publisher._prepare_plan_item(snapshot, pinned, item, roots, 0)
    recycled = prepared[0]
    assert recycled.backup is not None
    os.replace(recycled.source, recycled.backup)
    await store.transition_file_mutation_journal(
        recycled.journal.id,
        expected_state="validated",
        new_state="source_backed_up",
        expected_row_revision=recycled.journal.row_revision,
        updated_at=116.0,
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE library_operation_jobs SET lease_expires_at=0 WHERE id=?",
            (handle.job_id,),
        )

    result = await LibraryManagementRecoveryService(
        store, publisher, filesystem, clock=lambda: 200.0
    ).recover_startup()

    track = await store.get_target_track("track-1")
    journals = await store.list_file_mutation_journals_for_bundle(handle.job_id, 0)
    assert result.recovered_bundles == 1
    assert source.exists() is False
    assert track is not None and track["root_id"] == MANAGEMENT_RECYCLE_ROOT_ID
    assert Path(str(track["file_path"])).read_bytes() == original_bytes
    assert recycle in Path(str(track["file_path"])).parents
    assert [value.state for value in journals] == ["completed"]


@pytest.mark.asyncio
async def test_recycled_tracked_file_remains_eligible_for_ordinary_undo(
    tmp_path: Path,
) -> None:
    (
        _root,
        _source,
        _occupied,
        _recycle,
        preferences,
        store,
        planner,
        service,
        source_job_id,
        source_revision,
        settings_revision,
        policy_revision,
        filesystem,
    ) = await _collision_preview(tmp_path)
    handle = await _create_resolution(
        service,
        store,
        source_job_id=source_job_id,
        source_revision=source_revision,
        settings_revision=settings_revision,
        policy_revision=policy_revision,
        action="recycle_incoming_keep_existing",
        key="recycle-before-undo",
    )
    await _begin_and_publish(tmp_path, handle, store, preferences, planner, filesystem)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE library_operation_jobs SET state='succeeded',terminal_at=116,"
            "lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=116,"
            "row_revision=row_revision+1,event_revision=event_revision+1 WHERE id=?",
            (handle.job_id,),
        )
    source_job = await store.get_operation_job(handle.job_id)
    assert source_job is not None
    audio = AudioMetadataEngine()
    undo = LibraryManagementUndoService(
        store,
        preferences,
        audio,
        LibraryManagementBlobStore(tmp_path / "blobs", store),
        filesystem,
        clock=lambda: 120.0,
    )
    preview = await undo.create_preview(
        handle.job_id,
        LibraryManagementUndoPreviewRequest(
            expected_operation_row_revision=int(source_job["row_revision"]),
            idempotency_key="undo-recycled-track",
        ),
        "admin",
    )
    claimed = await store.claim_operation_job(
        "undo-recycled-worker",
        now=121.0,
        lease_seconds=60.0,
        kind="library_management",
    )
    assert claimed is not None
    await undo.run_claimed_preview(claimed, "undo-recycled-worker")
    item = (await store.list_library_management_plan_items(preview.job_id))[0]

    assert item.eligibility == "eligible"
    assert item.expected_root_id == MANAGEMENT_RECYCLE_ROOT_ID
    assert item.destination_root_id == "root-1"
