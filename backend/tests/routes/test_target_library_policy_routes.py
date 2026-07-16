from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException

from api.v1.routes.library_policies_target import router
from api.v1.schemas.library_policies import (
    LibraryPathMappingReport,
    LibraryPolicyApplyPreviewResponse,
    LibraryPolicyImpactResponse,
    LibraryPolicyTreeResponse,
    LibraryPolicyTreeNode,
    LibrarySettingsResponse,
)
from core.dependencies import get_library_policy_service
from core.dependencies.service_providers import get_target_library_policy_service
from middleware import _get_current_admin
from tests.helpers import build_test_client, override_admin_auth


@pytest.fixture
def app() -> tuple[FastAPI, AsyncMock, Mock]:
    application = FastAPI()
    application.include_router(router)
    target = AsyncMock()
    target.get_settings.return_value = LibrarySettingsResponse(
        policy_revision="policy-2",
        reconciliation_required=True,
        reconciliation_state="awaiting_reconciliation",
        pending_policy_revision="policy-2",
        affected_scope_ids=["root"],
    )
    target.save_settings.return_value = target.get_settings.return_value
    target.preview_apply.return_value = LibraryPolicyApplyPreviewResponse(
        policy_revision="policy-2",
        scope_ids=["root"],
        estimated_file_count=12,
    )
    target.policy_tree.return_value = LibraryPolicyTreeResponse(
        policy_revision="policy-2",
        roots=[
            LibraryPolicyTreeNode(
                id="root",
                kind="root",
                label="Music",
                path="/music",
                policy="automatic",
                indexed_file_count=12,
                on_disk_file_count=14,
            )
        ],
    )
    base = Mock()
    base.policy_tree.return_value = LibraryPolicyTreeResponse(
        policy_revision="policy-2", roots=[]
    )
    base.preview_impact.return_value = LibraryPolicyImpactResponse(
        current_policy_revision="policy-1",
        proposed_policy_revision="policy-2",
        stale=False,
        reconciliation_required=True,
        affected_scope_ids=["root"],
    )
    base.dry_run_path_mapping = AsyncMock(
        return_value=LibraryPathMappingReport(
            policy_revision="policy-2",
            source_count=0,
            mapped_count=0,
            ambiguous_count=0,
            out_of_root_count=0,
            blocking=False,
            items=[],
        )
    )
    application.dependency_overrides[get_target_library_policy_service] = lambda: target
    application.dependency_overrides[get_library_policy_service] = lambda: base
    return application, target, base


def test_target_policy_routes_preserve_pending_state_and_preview_apply(
    app: tuple[FastAPI, AsyncMock, Mock],
) -> None:
    application, target, _ = app
    override_admin_auth(application)
    client = build_test_client(application)
    response = client.get("/settings/library")
    saved = client.put(
        "/settings/library",
        json={
            "settings": {"library_roots": []},
            "expected_policy_revision": "policy-2",
        },
    )
    preview = client.post(
        "/settings/library/policy-apply-preview",
        json={"scope_ids": ["root"], "expected_policy_revision": "policy-2"},
    )
    tree = client.get("/settings/library/policy-tree")
    assert response.status_code == 200
    assert response.json()["reconciliation_state"] == "awaiting_reconciliation"
    assert saved.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["estimated_file_count"] == 12
    assert tree.json()["roots"][0]["indexed_file_count"] == 12
    target.policy_tree.assert_awaited_once()
    target.save_settings.assert_awaited_once_with(
        target.save_settings.await_args.args[0],
        expected_policy_revision="policy-2",
    )


def test_target_policy_routes_are_admin_only(
    app: tuple[FastAPI, AsyncMock, Mock],
) -> None:
    application, _, _ = app

    def reject_admin() -> None:
        raise HTTPException(status_code=403, detail="Admin access required")

    application.dependency_overrides[_get_current_admin] = reject_admin
    client = build_test_client(application)
    assert client.get("/settings/library").status_code == 403
    assert (
        client.post(
            "/settings/library/policy-apply-preview",
            json={"scope_ids": ["root"], "expected_policy_revision": "policy-2"},
        ).status_code
        == 403
    )

    unauthenticated = FastAPI()
    unauthenticated.include_router(router)
    assert (
        build_test_client(unauthenticated).get("/settings/library").status_code == 401
    )


def test_target_policy_route_inventory_is_complete() -> None:
    inventory = {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST", "PUT"}
    }
    assert inventory == {
        ("GET", "/settings/library"),
        ("PUT", "/settings/library"),
        ("GET", "/settings/library/policy-tree"),
        ("POST", "/settings/library/policy-impact"),
        ("POST", "/settings/library/policy-apply-preview"),
    }
