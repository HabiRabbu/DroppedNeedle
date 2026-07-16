"""Target-only settings boundary with durable policy reconciliation state."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import msgspec

from api.v1.schemas.library_policies import (
    LibraryPolicyApplyPreviewResponse,
    LibraryPolicyApplyRequest,
    LibraryPolicyImpactRequest,
    LibraryPolicyImpactResponse,
    LibrarySettingsResponse,
    LibraryPolicyTreeResponse,
    TypedLibrarySettings,
)
from core.exceptions import TargetStartupInvariantError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.library_policy_reconciliation_service import (
    LibraryPolicyReconciliationService,
)
from services.native.library_policy_service import LibraryPolicyService
from services.native.library_policy_resolver import LibraryPolicyResolver


class TargetLibraryPolicyService:
    def __init__(
        self,
        settings: LibraryPolicyService,
        reconciliation: LibraryPolicyReconciliationService,
        store: NativeLibraryStore,
        *,
        on_settings_saved: Callable[[], None] | None = None,
        transition_lock: asyncio.Lock | None = None,
    ) -> None:
        self._settings = settings
        self._reconciliation = reconciliation
        self._store = store
        self._on_settings_saved = on_settings_saved
        self._save_lock = transition_lock or asyncio.Lock()

    @staticmethod
    def _settings_json(settings: TypedLibrarySettings) -> str:
        payload = msgspec.to_builtins(settings)
        payload["acoustid_api_key"] = ""
        return msgspec.json.encode(payload).decode()

    async def recover_pending_transition(self) -> bool:
        async with self._save_lock:
            transition = await self._store.get_policy_transition()
            if transition is None or transition["state"] != "prepared":
                return False
            current_revision = LibraryPolicyResolver(
                self._settings.current_settings()
            ).policy_revision
            proposed_revision = transition["proposed_policy_revision"]
            if current_revision == transition["previous_policy_revision"]:
                await self._reconciliation.abort_boundary(
                    proposed_policy_revision=proposed_revision
                )
                return True
            if current_revision != proposed_revision:
                raise TargetStartupInvariantError(
                    "The library policy transition does not match the saved configuration."
                )
            if self._on_settings_saved is not None:
                self._on_settings_saved()
            await self._reconciliation.commit_boundary(
                proposed_policy_revision=proposed_revision
            )
            return True

    async def get_settings(self) -> LibrarySettingsResponse:
        response = self._settings.get_settings()
        pending = await self._store.get_pending_policy()
        if pending is None or not pending["pending_scope_ids"]:
            return response
        payload = msgspec.to_builtins(response)
        payload.update(
            {
                "reconciliation_required": True,
                "reconciliation_state": "awaiting_reconciliation",
                "pending_policy_revision": pending["desired_policy_revision"],
                "affected_scope_ids": pending["pending_scope_ids"],
            }
        )
        return LibrarySettingsResponse(**payload)

    async def save_settings(
        self,
        settings: TypedLibrarySettings,
        *,
        expected_policy_revision: str,
    ) -> LibrarySettingsResponse:
        async with self._save_lock:
            previous_settings = self._settings.current_settings()
            previous_settings_raw = self._settings.current_settings_raw()
            previous_revision = LibraryPolicyResolver(previous_settings).policy_revision
            proposed, changed_scopes = self._settings.prepare_change(
                settings,
                expected_policy_revision=expected_policy_revision,
            )
            previous_pending = await self._store.get_pending_policy()
            pending_scopes = (
                self._settings.rebase_scopes(
                    previous_pending["pending_scopes"], proposed
                )
                if previous_pending is not None
                else []
            )
            merged = {
                (scope.root_id, scope.relative_path): scope
                for scope in [*pending_scopes, *changed_scopes]
            }
            scopes = self._settings.collapse_scopes(list(merged.values()))
            prepare_task = asyncio.create_task(
                self._reconciliation.prepare_boundary(
                    previous_policy_revision=previous_revision,
                    proposed_policy_revision=proposed.policy_revision,
                    previous_settings_json=self._settings_json(previous_settings),
                    proposed_settings_json=self._settings_json(proposed.settings),
                    scopes=scopes,
                )
            )
            try:
                await asyncio.shield(prepare_task)
            except asyncio.CancelledError:
                await prepare_task
                await self._reconciliation.abort_boundary(
                    proposed_policy_revision=proposed.policy_revision
                )
                raise
            config_persisted = False
            try:
                self._settings.persist_settings(
                    proposed.settings,
                    expected_policy_revision=expected_policy_revision,
                )
                config_persisted = True
                if self._on_settings_saved is not None:
                    self._on_settings_saved()
            except Exception:
                if config_persisted:
                    self._settings.persist_settings(
                        previous_settings_raw,
                        expected_policy_revision=proposed.policy_revision,
                    )
                    if self._on_settings_saved is not None:
                        self._on_settings_saved()
                await self._reconciliation.abort_boundary(
                    proposed_policy_revision=proposed.policy_revision
                )
                raise
            commit_task = asyncio.create_task(
                self._reconciliation.commit_boundary(
                    proposed_policy_revision=proposed.policy_revision
                )
            )
            cancelled = False
            try:
                try:
                    immediate = await asyncio.shield(commit_task)
                except asyncio.CancelledError:
                    cancelled = True
                    immediate = await commit_task
            except Exception:
                self._settings.persist_settings(
                    previous_settings_raw,
                    expected_policy_revision=proposed.policy_revision,
                )
                if self._on_settings_saved is not None:
                    self._on_settings_saved()
                await self._reconciliation.abort_boundary(
                    proposed_policy_revision=proposed.policy_revision
                )
                raise
            if cancelled:
                raise asyncio.CancelledError
            current = await self.get_settings()
            payload = msgspec.to_builtins(current)
            payload["actions_applied"] = [
                "Settings saved. No library work was started.",
                (
                    f"{immediate['cancelled']} queued identification "
                    f"job{'s were' if immediate['cancelled'] != 1 else ' was'} stopped "
                    "because the new policy no longer allows the work."
                ),
            ]
            return LibrarySettingsResponse(**payload)

    async def policy_tree(self) -> LibraryPolicyTreeResponse:
        tree = self._settings.policy_tree()
        scopes = [
            (root.id, "." if node.kind == "root" else node.path)
            for root in tree.roots
            for node in [root, *root.children]
        ]
        counts = await self._store.get_policy_scope_counts(scopes)
        payload = msgspec.to_builtins(tree)
        for root in payload["roots"]:
            indexed, on_disk = counts[(root["id"], ".")]
            root["indexed_file_count"] = indexed
            root["on_disk_file_count"] = on_disk
            for child in root["children"]:
                indexed, on_disk = counts[(root["id"], child["path"])]
                child["indexed_file_count"] = indexed
                child["on_disk_file_count"] = on_disk
        return msgspec.convert(payload, type=LibraryPolicyTreeResponse)

    async def preview_impact(
        self, request: LibraryPolicyImpactRequest
    ) -> LibraryPolicyImpactResponse:
        response = self._settings.preview_impact(request)
        scopes = self._settings.preview_scopes(request.settings)
        indexed, on_disk = await self._store.get_policy_scope_total_counts(scopes)
        payload = msgspec.to_builtins(response)
        payload["indexed_file_count"] = indexed
        payload["on_disk_file_count"] = on_disk
        return LibraryPolicyImpactResponse(**payload)

    async def preview_apply(
        self, request: LibraryPolicyApplyRequest
    ) -> LibraryPolicyApplyPreviewResponse:
        preview = await self._reconciliation.preview_apply(
            request.scope_ids,
            expected_policy_revision=request.expected_policy_revision,
        )
        pending = await self._store.get_pending_policy()
        return LibraryPolicyApplyPreviewResponse(
            policy_revision=str(preview["policy_revision"]),
            scope_ids=[str(value) for value in preview["scope_ids"]],
            estimated_file_count=int(preview["estimated_file_count"]),
            content_will_become_unavailable=any(
                scope.effective_policy == "excluded" for scope in preview["scopes"]
            ),
            queued_work_was_cancelled_on_save=bool(
                pending and pending["cancelled_work_count"]
            ),
        )
