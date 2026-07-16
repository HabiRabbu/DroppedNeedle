"""Typed library-root and policy contracts for the target application."""

from __future__ import annotations

from typing import Literal

import msgspec

from api.v1.schemas.settings import DEFAULT_NAMING_TEMPLATE
from infrastructure.msgspec_fastapi import AppStruct

LibraryIdentificationPolicy = Literal["local_metadata", "automatic", "excluded"]


class LibraryPathPolicyRule(AppStruct):
    id: str
    relative_path: str
    policy: LibraryIdentificationPolicy


class LibraryRootSettings(AppStruct):
    id: str
    path: str
    label: str
    policy: LibraryIdentificationPolicy = "automatic"
    rules: list[LibraryPathPolicyRule] = msgspec.field(default_factory=list)


class TypedLibrarySettings(AppStruct):
    library_roots: list[LibraryRootSettings] = msgspec.field(default_factory=list)
    staging_path: str = ""
    naming_template: str = DEFAULT_NAMING_TEMPLATE
    acoustid_api_key: str = ""


class LibrarySettingsResponse(TypedLibrarySettings):
    policy_revision: str = ""
    reconciliation_required: bool = False
    reconciliation_state: Literal["applied", "awaiting_reconciliation"] = "applied"
    pending_policy_revision: str | None = None
    affected_scope_ids: list[str] = msgspec.field(default_factory=list)
    actions_applied: list[str] = msgspec.field(default_factory=list)
    warnings: list[str] = msgspec.field(default_factory=list)


class LibrarySettingsUpdateRequest(AppStruct):
    settings: TypedLibrarySettings
    expected_policy_revision: str


class LibraryPolicyTreeNode(AppStruct):
    id: str
    kind: Literal["root", "rule"]
    label: str
    path: str
    policy: LibraryIdentificationPolicy
    inherited_from_id: str | None = None
    available: bool = True
    indexed_file_count: int | None = None
    on_disk_file_count: int | None = None
    children: list["LibraryPolicyTreeNode"] = msgspec.field(default_factory=list)


class LibraryPolicyTreeResponse(AppStruct):
    policy_revision: str
    roots: list[LibraryPolicyTreeNode]
    warnings: list[str] = msgspec.field(default_factory=list)


class LibraryPolicyImpactRequest(AppStruct):
    settings: TypedLibrarySettings
    expected_policy_revision: str | None = None


class LibraryPolicyImpactResponse(AppStruct):
    current_policy_revision: str
    proposed_policy_revision: str
    stale: bool
    reconciliation_required: bool
    affected_scope_ids: list[str]
    indexed_file_count: int | None = None
    on_disk_file_count: int | None = None
    content_will_become_unavailable: bool = False
    queued_work_will_be_cancelled: bool = False
    warnings: list[str] = msgspec.field(default_factory=list)


class LibraryPolicyApplyRequest(AppStruct):
    scope_ids: list[str]
    expected_policy_revision: str


class LibraryPolicyApplyPreviewResponse(AppStruct):
    policy_revision: str
    scope_ids: list[str]
    estimated_file_count: int
    content_will_become_unavailable: bool = False
    queued_work_was_cancelled_on_save: bool = False


class LibraryPathMappingItem(AppStruct):
    source_kind: Literal["library_file", "review_row"]
    source_id: str
    absolute_path: str
    root_id: str | None = None
    relative_path: str | None = None
    error: Literal["ambiguous", "out_of_root"] | None = None


class LibraryPathMappingReport(AppStruct):
    policy_revision: str
    source_count: int
    mapped_count: int
    ambiguous_count: int
    out_of_root_count: int
    blocking: bool
    items: list[LibraryPathMappingItem]
