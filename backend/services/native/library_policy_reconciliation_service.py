"""Desired/applied target policy transition and explicit reconciliation boundary."""

from __future__ import annotations

import time
from collections.abc import Callable

from core.exceptions import StaleRevisionError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_work import ScanRequest, ScanRequestResult, ScanScope
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_scan_coordinator import LibraryScanCoordinator


class LibraryPolicyReconciliationService:
    def __init__(
        self,
        store: NativeLibraryStore,
        resolver_getter: Callable[[], LibraryPolicyResolver],
        coordinator: LibraryScanCoordinator,
    ) -> None:
        self._store = store
        self._resolver_getter = resolver_getter
        self._coordinator = coordinator

    async def save_boundary(
        self,
        scopes: list[ScanScope],
        *,
        policy_revision: str,
        now: float | None = None,
    ) -> dict[str, int]:
        """Apply only immediate desired-policy suppression; never start a scan."""
        timestamp = time.time() if now is None else now
        return await self._store.save_policy_boundary(
            scopes=scopes,
            policy_revision=policy_revision,
            updated_at=timestamp,
        )

    async def prepare_boundary(
        self,
        *,
        previous_policy_revision: str,
        proposed_policy_revision: str,
        previous_settings_json: str,
        proposed_settings_json: str,
        scopes: list[ScanScope],
        now: float | None = None,
    ) -> None:
        await self._store.prepare_policy_transition(
            previous_policy_revision=previous_policy_revision,
            proposed_policy_revision=proposed_policy_revision,
            previous_settings_json=previous_settings_json,
            proposed_settings_json=proposed_settings_json,
            scopes=scopes,
            prepared_at=time.time() if now is None else now,
        )

    async def commit_boundary(
        self, *, proposed_policy_revision: str, now: float | None = None
    ) -> dict[str, int]:
        return await self._store.commit_policy_transition(
            proposed_policy_revision=proposed_policy_revision,
            updated_at=time.time() if now is None else now,
        )

    async def abort_boundary(
        self, *, proposed_policy_revision: str, now: float | None = None
    ) -> None:
        await self._store.abort_policy_transition(
            proposed_policy_revision=proposed_policy_revision,
            aborted_at=time.time() if now is None else now,
        )

    async def preview_apply(
        self, scope_ids: list[str], *, expected_policy_revision: str
    ) -> dict:
        resolver = self._resolver_getter()
        if resolver.policy_revision != expected_policy_revision:
            raise StaleRevisionError(
                "The library policy changed. Preview the reconciliation again."
            )
        pending = await self._store.get_pending_policy()
        if (
            pending is not None
            and pending["desired_policy_revision"] == expected_policy_revision
            and pending["pending_scopes"]
        ):
            selected = set(scope_ids)
            scopes = [
                scope
                for scope in pending["pending_scopes"]
                if not selected or scope.scope_id in selected
            ]
            available = {
                scope.scope_id
                for scope in pending["pending_scopes"]
                if scope.scope_id is not None
            }
            if selected - available:
                raise ValidationError(
                    "One or more library policy scopes are no longer pending."
                )
        else:
            scopes = self._scopes(resolver, scope_ids)
        return {
            "policy_revision": resolver.policy_revision,
            "scope_ids": scope_ids,
            "estimated_file_count": await self._store.estimate_scan_scope(scopes),
            "scopes": scopes,
        }

    async def apply(
        self,
        scope_ids: list[str],
        *,
        expected_policy_revision: str,
        requested_by_user_id: str,
    ) -> ScanRequestResult:
        preview = await self.preview_apply(
            scope_ids, expected_policy_revision=expected_policy_revision
        )
        return await self._coordinator.request_run(
            ScanRequest(
                kind="policy_reconcile",
                trigger="policy_apply",
                scopes=preview["scopes"],
                requested_by_user_id=requested_by_user_id,
                policy_revision=expected_policy_revision,
            )
        )

    @staticmethod
    def _scopes(
        resolver: LibraryPolicyResolver, scope_ids: list[str]
    ) -> list[ScanScope]:
        selected = set(scope_ids)
        scopes: list[ScanScope] = []
        for root in resolver.settings.library_roots:
            if not selected or root.id in selected:
                scopes.append(
                    ScanScope(
                        root_id=root.id,
                        scope_id=root.id,
                        relative_path=".",
                        root_path=root.path,
                        effective_policy=root.policy,
                        policy_revision=resolver.policy_revision,
                    )
                )
                continue
            for rule in root.rules:
                if rule.id in selected:
                    scopes.append(
                        ScanScope(
                            root_id=root.id,
                            scope_id=rule.id,
                            relative_path=rule.relative_path,
                            root_path=root.path,
                            effective_policy=rule.policy,
                            policy_revision=resolver.policy_revision,
                        )
                    )
        if selected and len(scopes) != len(selected):
            raise ValidationError("One or more library policy scopes no longer exist.")
        return scopes
