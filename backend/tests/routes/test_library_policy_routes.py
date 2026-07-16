from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException

from api.v1.routes.library_policies import router
from api.v1.schemas.library_policies import (
    LibraryPathMappingReport,
    LibraryPolicyImpactResponse,
    LibraryPolicyTreeResponse,
    LibraryRootSettings,
    LibrarySettingsResponse,
)
from core.dependencies import get_library_policy_service
from core.exceptions import ConfigurationError
from middleware import _get_current_admin
from tests.helpers import build_test_client, mock_admin_user


@pytest.fixture
def service() -> MagicMock:
    root = LibraryRootSettings(id="root-1", path="/music", label="Music")
    mock = MagicMock()
    mock.get_settings.return_value = LibrarySettingsResponse(
        library_roots=[root], policy_revision="revision-1"
    )
    mock.save_settings.return_value = mock.get_settings.return_value
    mock.policy_tree.return_value = LibraryPolicyTreeResponse(
        policy_revision="revision-1", roots=[]
    )
    mock.preview_impact.return_value = LibraryPolicyImpactResponse(
        current_policy_revision="revision-1",
        proposed_policy_revision="revision-2",
        stale=False,
        reconciliation_required=True,
        affected_scope_ids=["root-1"],
    )
    mock.dry_run_path_mapping = AsyncMock(
        return_value=LibraryPathMappingReport(
            policy_revision="revision-1",
            source_count=0,
            mapped_count=0,
            ambiguous_count=0,
            out_of_root_count=0,
            blocking=False,
            items=[],
        )
    )
    return mock


def _client(service: MagicMock, admin_override=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_library_policy_service] = lambda: service
    if admin_override is not None:
        app.dependency_overrides[_get_current_admin] = admin_override
    return build_test_client(app)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/settings/library/roots", None),
        ("PUT", "/settings/library/roots", {"library_roots": []}),
        ("GET", "/settings/library/policy-tree", None),
        (
            "POST",
            "/settings/library/policy-impact",
            {"settings": {"library_roots": []}},
        ),
        ("GET", "/settings/library/path-mapping", None),
    ],
)
def test_library_policy_routes_require_admin(service, method, path, body) -> None:
    unauthenticated = _client(service).request(method, path, json=body)
    user = _client(
        service,
        admin_override=lambda: (_ for _ in ()).throw(
            HTTPException(status_code=403, detail="Admin access required")
        ),
    ).request(method, path, json=body)
    admin = _client(service, admin_override=mock_admin_user).request(
        method, path, json=body
    )

    assert unauthenticated.status_code == 401
    assert user.status_code == 403
    assert admin.status_code not in (401, 403)


def test_library_policy_route_contracts(service) -> None:
    client = _client(service, admin_override=mock_admin_user)

    roots = client.get("/settings/library/roots")
    saved = client.put(
        "/settings/library/roots",
        json={
            "settings": {
                "library_roots": [{"id": "root-1", "path": "/music", "label": "Music"}]
            },
            "expected_policy_revision": "revision-1",
        },
    )
    tree = client.get("/settings/library/policy-tree")
    impact = client.post(
        "/settings/library/policy-impact",
        json={"settings": {"library_roots": []}},
    )
    mapping = client.get("/settings/library/path-mapping")

    assert roots.json()["policy_revision"] == "revision-1"
    assert saved.status_code == 200
    assert tree.json()["roots"] == []
    assert impact.json()["affected_scope_ids"] == ["root-1"]
    assert mapping.json()["blocking"] is False


def test_library_policy_validation_uses_error_envelope(service) -> None:
    service.save_settings.side_effect = ConfigurationError("Library roots overlap.")
    response = _client(service, admin_override=mock_admin_user).put(
        "/settings/library/roots",
        json={
            "settings": {"library_roots": []},
            "expected_policy_revision": "revision-1",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "CONFIGURATION_ERROR",
            "message": "Library roots overlap.",
            "details": None,
        }
    }
