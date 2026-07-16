"""Typed library-root settings, previews, trees, and legacy-path dry runs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable

import msgspec

from api.v1.schemas.library_policies import (
    LibraryPathMappingItem,
    LibraryPathMappingReport,
    LibraryPolicyImpactRequest,
    LibraryPolicyImpactResponse,
    LibraryPolicyTreeNode,
    LibraryPolicyTreeResponse,
    LibrarySettingsResponse,
    TypedLibrarySettings,
)
from core.exceptions import ConfigurationError, StaleRevisionError
from models.library_work import ScanScope
from services.native.library_policy_resolver import LibraryPolicyResolver

if TYPE_CHECKING:
    from infrastructure.persistence.library_db import LibraryDB
    from services.preferences_service import PreferencesService


class LibraryPolicyService:
    def __init__(
        self,
        preferences: "PreferencesService",
        library_db: "LibraryDB | None",
        resolver_getter: Callable[[], LibraryPolicyResolver],
        resolver_clearer: Callable[[], None],
    ) -> None:
        self._preferences = preferences
        self._library_db = library_db
        self._resolver_getter = resolver_getter
        self._resolver_clearer = resolver_clearer

    def get_settings(self) -> LibrarySettingsResponse:
        resolver = self._resolver_getter()
        settings = self._preferences.get_typed_library_settings()
        return self._settings_response(settings, resolver)

    def save_settings(
        self,
        settings: TypedLibrarySettings,
        *,
        expected_policy_revision: str,
    ) -> LibrarySettingsResponse:
        proposed, scopes = self.prepare_change(
            settings, expected_policy_revision=expected_policy_revision
        )
        affected = self._scope_ids(scopes)
        self.persist_settings(
            proposed.settings,
            expected_policy_revision=expected_policy_revision,
        )
        self._resolver_clearer()
        saved = self._resolver_getter()
        masked = self._preferences.get_typed_library_settings()
        return self._settings_response(
            masked,
            saved,
            affected_scope_ids=affected,
            reconciliation_required=bool(affected),
            actions_applied=["Settings saved. No scan or reconciliation was started."],
        )

    def current_settings(self) -> TypedLibrarySettings:
        return self._resolver_getter().settings

    def current_settings_raw(self) -> TypedLibrarySettings:
        return self._preferences.get_typed_library_settings_raw()

    def persist_settings(
        self,
        settings: TypedLibrarySettings,
        *,
        expected_policy_revision: str,
    ) -> None:
        self._preferences.save_typed_library_settings_if_current(
            settings,
            expected_policy_revision=expected_policy_revision,
        )

    def policy_tree(self) -> LibraryPolicyTreeResponse:
        resolver = self._resolver_getter()
        roots: list[LibraryPolicyTreeNode] = []
        for root in resolver.settings.library_roots:
            root_path = Path(root.path)
            children = [
                LibraryPolicyTreeNode(
                    id=rule.id,
                    kind="rule",
                    label=PurePosixPath(rule.relative_path).name,
                    path=rule.relative_path,
                    policy=rule.policy,
                    inherited_from_id=rule.id,
                    available=(root_path / rule.relative_path).exists(),
                )
                for rule in root.rules
            ]
            roots.append(
                LibraryPolicyTreeNode(
                    id=root.id,
                    kind="root",
                    label=root.label,
                    path=root.path,
                    policy=root.policy,
                    inherited_from_id=root.id,
                    available=root_path.exists(),
                    children=children,
                )
            )
        return LibraryPolicyTreeResponse(
            policy_revision=resolver.policy_revision,
            roots=roots,
            warnings=resolver.warnings,
        )

    def preview_impact(
        self, request: LibraryPolicyImpactRequest
    ) -> LibraryPolicyImpactResponse:
        current = self._resolver_getter()
        proposed = LibraryPolicyResolver(request.settings)
        scopes = self._transition_scopes(current, proposed)
        affected = self._scope_ids(scopes)
        return LibraryPolicyImpactResponse(
            current_policy_revision=current.policy_revision,
            proposed_policy_revision=proposed.policy_revision,
            stale=(
                request.expected_policy_revision is not None
                and request.expected_policy_revision != current.policy_revision
            ),
            reconciliation_required=bool(affected),
            affected_scope_ids=affected,
            content_will_become_unavailable=any(
                scope.effective_policy == "excluded" for scope in scopes
            ),
            queued_work_will_be_cancelled=any(
                scope.effective_policy != "automatic" for scope in scopes
            ),
            warnings=proposed.warnings,
        )

    def prepare_change(
        self,
        settings: TypedLibrarySettings,
        *,
        expected_policy_revision: str,
    ) -> tuple[LibraryPolicyResolver, list[ScanScope]]:
        current = self._resolver_getter()
        if current.policy_revision != expected_policy_revision:
            raise StaleRevisionError(
                "The library settings changed. Refresh this page and try again."
            )
        proposed = LibraryPolicyResolver(settings)
        return proposed, self._transition_scopes(current, proposed)

    def preview_scopes(self, settings: TypedLibrarySettings) -> list[ScanScope]:
        return self._transition_scopes(
            self._resolver_getter(), LibraryPolicyResolver(settings)
        )

    @staticmethod
    def rebase_scopes(
        scopes: list[ScanScope], proposed: LibraryPolicyResolver
    ) -> list[ScanScope]:
        roots = {root.id: root for root in proposed.settings.library_roots}
        rebased: list[ScanScope] = []
        for scope in scopes:
            root = roots.get(scope.root_id)
            if root is None:
                rebased.append(
                    msgspec.structs.replace(
                        scope,
                        effective_policy="excluded",
                        policy_revision=proposed.policy_revision,
                    )
                )
                continue
            if scope.relative_path == ".":
                policy = root.policy
            else:
                resolution = proposed.resolve(Path(root.path) / scope.relative_path)
                policy = resolution.policy if resolution is not None else root.policy
            rebased.append(
                msgspec.structs.replace(
                    scope,
                    root_path=root.path,
                    effective_policy=policy,
                    policy_revision=proposed.policy_revision,
                )
            )
        return LibraryPolicyService.collapse_scopes(rebased)

    async def dry_run_path_mapping(self) -> LibraryPathMappingReport:
        if self._library_db is None:
            raise RuntimeError(
                "Legacy path mapping is unavailable in the target application"
            )
        resolver = self._resolver_getter()
        sources = await self._library_db.get_library_path_mapping_sources()
        items: list[LibraryPathMappingItem] = []
        ambiguous = 0
        out_of_root = 0
        mapped = 0
        for source_kind, source_id, absolute_path in sources:
            try:
                resolution = resolver.resolve(absolute_path)
            except ConfigurationError:
                ambiguous += 1
                items.append(
                    LibraryPathMappingItem(
                        source_kind=source_kind,
                        source_id=source_id,
                        absolute_path=absolute_path,
                        error="ambiguous",
                    )
                )
                continue
            if resolution is None:
                out_of_root += 1
                items.append(
                    LibraryPathMappingItem(
                        source_kind=source_kind,
                        source_id=source_id,
                        absolute_path=absolute_path,
                        error="out_of_root",
                    )
                )
                continue
            mapped += 1
            items.append(
                LibraryPathMappingItem(
                    source_kind=source_kind,
                    source_id=source_id,
                    absolute_path=absolute_path,
                    root_id=resolution.root_id,
                    relative_path=resolution.relative_path,
                )
            )
        return LibraryPathMappingReport(
            policy_revision=resolver.policy_revision,
            source_count=len(sources),
            mapped_count=mapped,
            ambiguous_count=ambiguous,
            out_of_root_count=out_of_root,
            blocking=bool(ambiguous or out_of_root),
            items=items,
        )

    @staticmethod
    def require_catalog_import_mapping(report: LibraryPathMappingReport) -> None:
        if report.blocking or report.mapped_count != report.source_count:
            raise ConfigurationError(
                "Catalog import is blocked until every legacy path maps to one library root."
            )

    @staticmethod
    def _settings_response(
        settings: TypedLibrarySettings,
        resolver: LibraryPolicyResolver,
        *,
        affected_scope_ids: list[str] | None = None,
        reconciliation_required: bool = False,
        actions_applied: list[str] | None = None,
    ) -> LibrarySettingsResponse:
        return LibrarySettingsResponse(
            library_roots=settings.library_roots,
            staging_path=settings.staging_path,
            naming_template=settings.naming_template,
            acoustid_api_key=settings.acoustid_api_key,
            policy_revision=resolver.policy_revision,
            reconciliation_required=reconciliation_required,
            reconciliation_state=(
                "awaiting_reconciliation" if reconciliation_required else "applied"
            ),
            pending_policy_revision=(
                resolver.policy_revision if reconciliation_required else None
            ),
            affected_scope_ids=affected_scope_ids or [],
            actions_applied=actions_applied or [],
            warnings=resolver.warnings,
        )

    @staticmethod
    def _transition_scopes(
        current: LibraryPolicyResolver, proposed: LibraryPolicyResolver
    ) -> list[ScanScope]:
        current_roots = {root.id: root for root in current.settings.library_roots}
        proposed_roots = {root.id: root for root in proposed.settings.library_roots}
        scopes: list[ScanScope] = []
        for root_id in sorted(set(current_roots) | set(proposed_roots)):
            old_root = current_roots.get(root_id)
            new_root = proposed_roots.get(root_id)
            if new_root is None:
                assert old_root is not None
                scopes.append(
                    ScanScope(
                        root_id=root_id,
                        scope_id=root_id,
                        relative_path=".",
                        root_path=old_root.path,
                        effective_policy="excluded",
                        policy_revision=proposed.policy_revision,
                    )
                )
                continue
            if (
                old_root is None
                or old_root.path != new_root.path
                or old_root.policy != new_root.policy
            ):
                scopes.append(
                    ScanScope(
                        root_id=root_id,
                        scope_id=root_id,
                        relative_path=".",
                        root_path=new_root.path,
                        effective_policy=new_root.policy,
                        policy_revision=proposed.policy_revision,
                    )
                )
                continue

            old_rules = {rule.id: rule for rule in old_root.rules}
            new_rules = {rule.id: rule for rule in new_root.rules}
            for rule_id in sorted(set(old_rules) | set(new_rules)):
                old_rule = old_rules.get(rule_id)
                new_rule = new_rules.get(rule_id)
                if old_rule == new_rule:
                    continue
                if old_rule is not None and (
                    new_rule is None or old_rule.relative_path != new_rule.relative_path
                ):
                    resolution = proposed.resolve(
                        Path(new_root.path) / old_rule.relative_path
                    )
                    scopes.append(
                        ScanScope(
                            root_id=root_id,
                            scope_id=rule_id,
                            relative_path=old_rule.relative_path,
                            root_path=new_root.path,
                            effective_policy=(
                                resolution.policy
                                if resolution is not None
                                else new_root.policy
                            ),
                            policy_revision=proposed.policy_revision,
                        )
                    )
                if new_rule is not None:
                    scopes.append(
                        ScanScope(
                            root_id=root_id,
                            scope_id=rule_id,
                            relative_path=new_rule.relative_path,
                            root_path=new_root.path,
                            effective_policy=new_rule.policy,
                            policy_revision=proposed.policy_revision,
                        )
                    )
        return LibraryPolicyService.collapse_scopes(scopes)

    @staticmethod
    def collapse_scopes(scopes: list[ScanScope]) -> list[ScanScope]:
        roots = {scope.root_id for scope in scopes if scope.relative_path == "."}
        unique: dict[tuple[str, str], ScanScope] = {}
        for scope in scopes:
            if scope.root_id in roots and scope.relative_path != ".":
                continue
            unique[(scope.root_id, scope.relative_path)] = scope
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _scope_ids(scopes: list[ScanScope]) -> list[str]:
        return sorted(
            {scope.scope_id for scope in scopes if scope.scope_id is not None}
        )
