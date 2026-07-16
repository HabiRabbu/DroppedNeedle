from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

import msgspec
import pytest

from api.v1.schemas.library_policies import (
    LibraryPolicyApplyRequest,
    LibraryRootSettings,
    LibrarySettingsResponse,
    TypedLibrarySettings,
)
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_work import ScanRequest, ScanScope
from services.native.target_library_policy_service import TargetLibraryPolicyService
from services.native.library_policy_resolver import LibraryPolicyResolver


@pytest.mark.asyncio
async def test_policy_pending_state_survives_refresh_and_clears_only_after_apply(
    tmp_path: Path,
) -> None:
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO auth_users(id) VALUES ('admin')")
    connection.close()
    store = NativeLibraryStore(path, threading.Lock())
    settings = TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root", path="/music", label="Music", policy="excluded"
            )
        ]
    )
    previous_settings = TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root", path="/music", label="Music", policy="automatic"
            )
        ]
    )
    current = LibrarySettingsResponse(
        library_roots=settings.library_roots,
        policy_revision="policy-2",
    )
    saved = LibrarySettingsResponse(
        library_roots=settings.library_roots,
        policy_revision="policy-2",
        reconciliation_required=True,
        reconciliation_state="awaiting_reconciliation",
        pending_policy_revision="policy-2",
        affected_scope_ids=["root"],
    )
    base = Mock()
    base.get_settings.return_value = current
    base.current_settings.return_value = previous_settings
    base.current_settings_raw.return_value = previous_settings
    scope = ScanScope(
        root_id="root",
        scope_id="root",
        root_path="/music",
        effective_policy="excluded",
        policy_revision="policy-2",
    )
    proposed = Mock(policy_revision="policy-2", settings=settings)
    base.prepare_change.return_value = (proposed, [scope])
    base.rebase_scopes.return_value = []
    base.collapse_scopes.side_effect = lambda scopes: scopes
    reconciliation = AsyncMock()

    async def commit_boundary(*, proposed_policy_revision: str) -> dict[str, int]:
        await store.record_pending_policy(
            policy_revision=proposed_policy_revision,
            scopes=[scope],
            changed_track_count=0,
            cancelled_work_count=1,
            updated_at=2,
        )
        return {"changed": 0, "cancelled": 1}

    reconciliation.commit_boundary.side_effect = commit_boundary
    reconciliation.preview_apply.return_value = {
        "policy_revision": "policy-2",
        "scope_ids": ["root"],
        "estimated_file_count": 12,
        "scopes": [scope],
    }
    on_settings_saved = Mock()
    service = TargetLibraryPolicyService(
        base,
        reconciliation,
        store,
        on_settings_saved=on_settings_saved,
    )

    response = await service.save_settings(
        settings, expected_policy_revision="policy-1"
    )
    refreshed = await service.get_settings()
    preview = await service.preview_apply(
        LibraryPolicyApplyRequest(
            scope_ids=["root"], expected_policy_revision="policy-2"
        )
    )
    assert response.reconciliation_state == "awaiting_reconciliation"
    assert response.affected_scope_ids == ["root"]
    assert response.actions_applied == [
        "Settings saved. No library work was started.",
        "1 queued identification job was stopped because the new policy no longer allows the work.",
    ]
    assert refreshed.reconciliation_required is True
    assert refreshed.pending_policy_revision == "policy-2"
    assert preview.estimated_file_count == 12
    assert preview.content_will_become_unavailable is True
    assert preview.queued_work_was_cancelled_on_save is True
    on_settings_saved.assert_called_once_with()

    requested = await store.request_scan_run(
        ScanRequest(
            kind="policy_reconcile",
            trigger="policy_apply",
            scopes=[
                ScanScope(
                    root_id="root",
                    scope_id="root",
                    root_path="/music",
                    effective_policy="excluded",
                    policy_revision="policy-2",
                )
            ],
            policy_revision="policy-2",
            requested_by_user_id="admin",
        ),
        run_id="policy-apply",
        requested_at=3,
    )
    run = await store.transition_scan_run(
        requested.run_id,
        expected_state="queued",
        expected_revision=requested.row_revision,
        new_state="discovering",
        now=4,
    )
    for expected, target in (
        ("discovering", "indexing"),
        ("indexing", "reconciling"),
        ("reconciling", "completed"),
    ):
        run = await store.transition_scan_run(
            run.id,
            expected_state=expected,
            expected_revision=run.row_revision,
            new_state=target,
            now=run.updated_at + 1,
        )
    applied = await service.get_settings()
    assert applied.reconciliation_required is False
    assert applied.reconciliation_state == "applied"
    assert applied.pending_policy_revision is None


@pytest.mark.asyncio
async def test_policy_boundary_failure_restores_config_and_aborts_journal() -> None:
    previous = TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root", path="/music", label="Music", policy="automatic"
            )
        ]
    )
    proposed_settings = msgspec.structs.replace(
        previous,
        library_roots=[
            msgspec.structs.replace(previous.library_roots[0], policy="excluded")
        ],
    )
    proposed = LibraryPolicyResolver(proposed_settings)
    base = Mock()
    base.current_settings.return_value = previous
    base.current_settings_raw.return_value = previous
    base.prepare_change.return_value = (proposed, [])
    base.rebase_scopes.return_value = []
    base.collapse_scopes.return_value = []
    reconciliation = AsyncMock()
    reconciliation.commit_boundary.side_effect = RuntimeError("database unavailable")
    store = AsyncMock()
    store.get_pending_policy.return_value = None
    on_settings_saved = Mock()
    service = TargetLibraryPolicyService(
        base,
        reconciliation,
        store,
        on_settings_saved=on_settings_saved,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.save_settings(
            proposed_settings,
            expected_policy_revision=LibraryPolicyResolver(previous).policy_revision,
        )

    assert base.persist_settings.call_args_list == [
        call(
            proposed.settings,
            expected_policy_revision=LibraryPolicyResolver(previous).policy_revision,
        ),
        call(
            previous,
            expected_policy_revision=proposed.policy_revision,
        ),
    ]
    assert on_settings_saved.call_count == 2
    reconciliation.abort_boundary.assert_awaited_once_with(
        proposed_policy_revision=proposed.policy_revision
    )


@pytest.mark.asyncio
async def test_startup_finishes_a_config_committed_policy_transition() -> None:
    settings = TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root", path="/music", label="Music", policy="excluded"
            )
        ]
    )
    revision = LibraryPolicyResolver(settings).policy_revision
    base = Mock()
    base.current_settings.return_value = settings
    reconciliation = AsyncMock()
    store = AsyncMock()
    store.get_policy_transition.return_value = {
        "state": "prepared",
        "previous_policy_revision": "previous",
        "proposed_policy_revision": revision,
    }
    on_settings_saved = Mock()
    service = TargetLibraryPolicyService(
        base,
        reconciliation,
        store,
        on_settings_saved=on_settings_saved,
    )

    assert await service.recover_pending_transition() is True
    on_settings_saved.assert_called_once_with()
    reconciliation.commit_boundary.assert_awaited_once_with(
        proposed_policy_revision=revision
    )
    reconciliation.abort_boundary.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_policy_saves_commit_in_revision_order() -> None:
    root = LibraryRootSettings(
        id="root", path="/music", label="Music", policy="automatic"
    )
    versions = [
        TypedLibrarySettings(library_roots=[root]),
        TypedLibrarySettings(
            library_roots=[msgspec.structs.replace(root, policy="excluded")]
        ),
        TypedLibrarySettings(
            library_roots=[msgspec.structs.replace(root, policy="local_metadata")]
        ),
    ]
    revisions = [LibraryPolicyResolver(value).policy_revision for value in versions]
    state = {"settings": versions[0]}
    base = Mock()
    base.current_settings.side_effect = lambda: state["settings"]
    base.current_settings_raw.side_effect = lambda: state["settings"]

    def prepare(settings, *, expected_policy_revision):
        assert (
            LibraryPolicyResolver(state["settings"]).policy_revision
            == expected_policy_revision
        )
        return LibraryPolicyResolver(settings), []

    def persist(settings, *, expected_policy_revision):
        assert (
            LibraryPolicyResolver(state["settings"]).policy_revision
            == expected_policy_revision
        )
        state["settings"] = settings

    def response():
        resolver = LibraryPolicyResolver(state["settings"])
        return LibrarySettingsResponse(
            library_roots=resolver.settings.library_roots,
            policy_revision=resolver.policy_revision,
        )

    base.prepare_change.side_effect = prepare
    base.persist_settings.side_effect = persist
    base.rebase_scopes.return_value = []
    base.collapse_scopes.return_value = []
    base.get_settings.side_effect = response
    store = AsyncMock()
    store.get_pending_policy.return_value = None
    first_commit_started = asyncio.Event()
    allow_first_commit = asyncio.Event()
    commits: list[str] = []
    reconciliation = AsyncMock()

    async def commit(*, proposed_policy_revision):
        commits.append(proposed_policy_revision)
        if proposed_policy_revision == revisions[1]:
            first_commit_started.set()
            await allow_first_commit.wait()
        return {"changed": 0, "cancelled": 0}

    reconciliation.commit_boundary.side_effect = commit
    service = TargetLibraryPolicyService(base, reconciliation, store)

    first = asyncio.create_task(
        service.save_settings(versions[1], expected_policy_revision=revisions[0])
    )
    await first_commit_started.wait()
    second = asyncio.create_task(
        service.save_settings(versions[2], expected_policy_revision=revisions[1])
    )
    await asyncio.sleep(0)
    assert commits == [revisions[1]]
    allow_first_commit.set()
    await asyncio.gather(first, second)

    assert commits == [revisions[1], revisions[2]]
    assert state["settings"] == versions[2]


@pytest.mark.asyncio
async def test_cancelled_prepare_is_awaited_and_aborted_before_unlocking() -> None:
    previous = TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root", path="/music", label="Music", policy="automatic"
            )
        ]
    )
    proposed_settings = TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root", path="/music", label="Music", policy="excluded"
            )
        ]
    )
    proposed = LibraryPolicyResolver(proposed_settings)
    base = Mock()
    base.current_settings.return_value = previous
    base.current_settings_raw.return_value = previous
    base.prepare_change.return_value = (proposed, [])
    base.rebase_scopes.return_value = []
    base.collapse_scopes.return_value = []
    store = AsyncMock()
    store.get_pending_policy.return_value = None
    prepare_started = asyncio.Event()
    allow_prepare = asyncio.Event()
    reconciliation = AsyncMock()

    async def prepare(**_kwargs):
        prepare_started.set()
        await allow_prepare.wait()

    reconciliation.prepare_boundary.side_effect = prepare
    service = TargetLibraryPolicyService(base, reconciliation, store)
    save = asyncio.create_task(
        service.save_settings(
            proposed_settings,
            expected_policy_revision=LibraryPolicyResolver(previous).policy_revision,
        )
    )
    await prepare_started.wait()
    save.cancel()
    await asyncio.sleep(0)
    assert not save.done()
    allow_prepare.set()

    with pytest.raises(asyncio.CancelledError):
        await save
    reconciliation.abort_boundary.assert_awaited_once_with(
        proposed_policy_revision=proposed.policy_revision
    )
    base.persist_settings.assert_not_called()
