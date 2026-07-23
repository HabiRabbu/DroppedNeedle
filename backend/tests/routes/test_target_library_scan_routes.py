from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException

from api.v1.routes.library_scan_target import router
from api.v1.schemas.library_policies import (
    LibraryPathPolicyRule,
    LibraryRootSettings,
    TypedLibrarySettings,
)
from core.dependencies import (
    get_library_policy_resolver,
    get_target_identification_queue,
    get_target_library_scan_coordinator,
)
from core.exceptions import ResourceNotFoundError, StaleRevisionError
from middleware import _get_current_admin
from models.library_work import ScanControlResult, ScanRequestResult
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_activity_events import activity_events
from tests.helpers import build_test_client, override_admin_auth, override_user_auth


@pytest.fixture
def resolver(tmp_path) -> LibraryPolicyResolver:
    root = tmp_path / "music"
    root.mkdir()
    return LibraryPolicyResolver(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(
                    id="root-a",
                    path=str(root),
                    label="Library",
                    rules=[
                        LibraryPathPolicyRule(
                            id="parent", relative_path="Artist", policy="automatic"
                        ),
                        LibraryPathPolicyRule(
                            id="child",
                            relative_path="Artist/Album",
                            policy="automatic",
                        ),
                    ],
                )
            ]
        )
    )


@pytest.fixture
def coordinator() -> AsyncMock:
    service = AsyncMock()
    service.current.return_value = []
    service.history.return_value = []
    service.history_page.return_value = ([], None)
    service.estimate.return_value = (12, 10.0)
    service.request_run.return_value = ScanRequestResult(
        run_id="run-1",
        disposition="started",
        state="queued",
        row_revision=1,
    )
    service.control.return_value = ScanControlResult(
        run_id="run-1",
        state="pausing",
        row_revision=2,
        event_revision=1,
        stream_revision=3,
    )
    return service


@pytest.fixture
def identification_queue() -> AsyncMock:
    service = AsyncMock()
    service.activity_snapshot.return_value = {
        "control_state": "running",
        "control_revision": 1,
        "counts": {},
        "started_at": None,
        "updated_at": None,
        "deferred_count": 0,
        "failure_event_id": None,
        "failure_at": None,
        "foreground_operation_count": 0,
    }
    service.stream_revisions.return_value = {
        "scan": 0,
        "identification": 0,
        "operation": 0,
    }
    service.pause.return_value = 2
    service.resume.return_value = 3
    return service


@pytest.fixture
def app(
    coordinator: AsyncMock,
    identification_queue: AsyncMock,
    resolver: LibraryPolicyResolver,
) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_target_library_scan_coordinator] = (
        lambda: coordinator
    )
    application.dependency_overrides[get_library_policy_resolver] = lambda: resolver
    application.dependency_overrides[get_target_identification_queue] = (
        lambda: identification_queue
    )
    return application


@pytest.fixture
def admin_client(app: FastAPI):
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    return build_test_client(app)


def test_start_accepts_scope_ids_and_never_accepts_a_path(
    admin_client, coordinator: AsyncMock, resolver: LibraryPolicyResolver
) -> None:
    response = admin_client.post(
        "/library/scan-runs",
        json={
            "kind": "incremental",
            "scope_ids": ["root-a"],
            "expected_policy_revision": resolver.policy_revision,
        },
    )
    assert response.status_code == 202
    assert response.json()["disposition"] == "started"
    request = coordinator.request_run.await_args.args[0]
    assert request.scopes[0].root_id == "root-a"
    assert request.scopes[0].relative_path == "."

    rejected = admin_client.post(
        "/library/scan-runs",
        json={
            "kind": "incremental",
            "scope_ids": ["/untrusted/path"],
            "expected_policy_revision": resolver.policy_revision,
        },
    )
    assert rejected.status_code == 400


def test_start_collapses_nested_selected_scopes_to_one_walk(
    admin_client, coordinator: AsyncMock, resolver: LibraryPolicyResolver
) -> None:
    response = admin_client.post(
        "/library/scan-runs",
        json={
            "kind": "incremental",
            "scope_ids": ["parent", "child"],
            "expected_policy_revision": resolver.policy_revision,
        },
    )

    assert response.status_code == 202
    request = coordinator.request_run.await_args.args[0]
    assert [(scope.scope_id, scope.relative_path) for scope in request.scopes] == [
        ("parent", "Artist")
    ]


def test_mutations_are_admin_only(
    app: FastAPI, resolver: LibraryPolicyResolver
) -> None:
    def reject_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[_get_current_admin] = reject_admin
    override_user_auth(app, role="user")
    client = build_test_client(app)
    body = {
        "kind": "incremental",
        "scope_ids": ["root-a"],
        "expected_policy_revision": resolver.policy_revision,
    }
    assert client.post("/library/scan-runs", json=body).status_code == 403
    assert (
        client.post(
            "/library/scan-runs/run-1/pause", json={"expected_revision": 1}
        ).status_code
        == 403
    )

    unauthenticated = FastAPI()
    unauthenticated.include_router(router)
    unauthenticated.dependency_overrides[get_target_library_scan_coordinator] = (
        lambda: coordinator
    )
    unauthenticated.dependency_overrides[get_library_policy_resolver] = lambda: resolver
    client = build_test_client(unauthenticated)
    assert client.post("/library/scan-runs", json=body).status_code == 401
    assert (
        client.post(
            "/library/scan-runs/run-1/stop", json={"expected_revision": 1}
        ).status_code
        == 401
    )


def test_activity_is_authenticated_and_redacted(
    app: FastAPI, coordinator: AsyncMock, identification_queue: AsyncMock
) -> None:
    unauthenticated = build_test_client(app)
    assert unauthenticated.get("/library/activity").status_code == 401
    assert unauthenticated.get("/library/activity/stream").status_code == 401

    coordinator.current.return_value = [
        SimpleNamespace(
            id="run-1",
            state="indexing",
            requested_by_user_id="admin-secret",
            aggregate_scope="private/path",
            updated_at=10,
            started_at=1,
        )
    ]
    coordinator.snapshot.return_value = SimpleNamespace(
        counters={"inspected_count": 4, "discovered_count": 10}
    )
    override_user_auth(app, role="user")
    response = build_test_client(app).get("/library/activity")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["label"] == "Updating the local library"
    assert payload["items"][0]["processed"] == 4
    encoded = response.text
    assert "admin-secret" not in encoded
    assert "private/path" not in encoded

    coordinator.current.return_value[0].state = "discovering"
    coordinator.snapshot.return_value = SimpleNamespace(
        counters={"inspected_count": 0, "discovered_count": 8}
    )
    discovering = build_test_client(app).get("/library/activity").json()["items"][0]
    assert discovering["processed"] == 8
    assert discovering["total"] is None
    assert discovering["indeterminate"] is True

    identification_queue.activity_snapshot.return_value = {
        "control_state": "paused",
        "control_revision": 8,
        "counts": {"queued": 6, "running": 1, "succeeded": 3, "needs_review": 2},
        "started_at": 2.0,
        "updated_at": 11.0,
        "deferred_count": 1,
        "kept_local_count": 4,
        "active_priority": 30,
        "failure_event_id": "failure-opaque",
        "failure_at": 9.0,
        "foreground_operation_count": 1,
    }
    payload = build_test_client(app).get("/library/activity").json()
    item = next(item for item in payload["items"] if item["kind"] == "identification")
    assert item == {
        "kind": "identification",
        "state": "pausing",
        "label": "Identifying albums",
        "processed": 5,
        "total": 12,
        "indeterminate": False,
        "updated_at": 11.0,
        "started_at": 2.0,
        "waiting_count": 7,
        "identified_count": 3,
        "kept_local_count": 4,
        "needs_review_count": 2,
        "failed_count": 0,
        "deferred_count": 1,
        "priority_band": "Administrator retries",
        "oldest_backlog_at": 2.0,
        "provider_unavailable": True,
        "control_revision": 8,
        "failure_event_id": "failure-opaque",
        "failure_at": 9.0,
        "foreground_operation_count": 1,
    }


def test_activity_projects_recent_scan_failure_and_foreground_work(
    app: FastAPI, coordinator: AsyncMock, identification_queue: AsyncMock
) -> None:
    import time

    failed = SimpleNamespace(
        id="failed-scan",
        state="failed",
        terminal_at=time.time() - 10,
        updated_at=time.time() - 10,
        started_at=time.time() - 20,
    )
    coordinator.history.return_value = [failed]
    coordinator.snapshot.return_value = SimpleNamespace(
        counters={"inspected_count": 3, "total_count": 5}
    )
    identification_queue.activity_snapshot.return_value = {
        **identification_queue.activity_snapshot.return_value,
        "foreground_operation_count": 1,
    }
    override_user_auth(app, role="user")
    items = build_test_client(app).get("/library/activity").json()["items"]
    scan = next(item for item in items if item["kind"] == "scan")
    identification = next(item for item in items if item["kind"] == "identification")
    assert scan["failure_event_id"] == "failed-scan"
    assert scan["processed"] == 3
    assert identification["foreground_operation_count"] == 1
    assert identification["state"] == "idle"
    assert identification["waiting_count"] == 0


def test_identification_controls_are_revisioned_and_admin_only(
    app: FastAPI, identification_queue: AsyncMock
) -> None:
    paused = dict(identification_queue.activity_snapshot.return_value)
    paused["control_state"] = "paused"
    running = dict(identification_queue.activity_snapshot.return_value)
    running["control_state"] = "running"
    identification_queue.activity_snapshot.side_effect = [paused, running]
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    client = build_test_client(app)
    response = client.post(
        "/library/identification/pause", json={"expected_revision": 1}
    )
    assert response.status_code == 200
    assert response.json() == {"state": "paused", "row_revision": 2}
    identification_queue.pause.assert_awaited_once_with(
        "test-admin-id", expected_revision=1
    )

    response = client.post(
        "/library/identification/resume", json={"expected_revision": 2}
    )
    assert response.status_code == 200
    assert response.json() == {"state": "running", "row_revision": 3}
    identification_queue.resume.assert_awaited_once_with(expected_revision=2)

    def reject_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[_get_current_admin] = reject_admin
    assert (
        build_test_client(app)
        .post("/library/identification/pause", json={"expected_revision": 1})
        .status_code
        == 403
    )


def test_control_and_history_contracts(admin_client, coordinator: AsyncMock) -> None:
    response = admin_client.post(
        "/library/scan-runs/run-1/pause", json={"expected_revision": 1}
    )
    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "state": "pausing",
        "row_revision": 2,
        "event_revision": 1,
        "stream_revision": 3,
    }
    assert admin_client.get("/library/scan-runs").json() == {
        "items": [],
        "next_cursor": None,
    }
    assert admin_client.get("/library/scan-runs/estimate").json() == {
        "approximate": True,
        "estimated_file_count": 12,
        "estimated_at": 10.0,
    }


def test_missing_and_stale_run_use_typed_error_envelopes(
    admin_client, coordinator: AsyncMock
) -> None:
    coordinator.snapshot.side_effect = ResourceNotFoundError("missing")
    response = admin_client.get("/library/scan-runs/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"

    coordinator.control.side_effect = StaleRevisionError("stale")
    response = admin_client.post(
        "/library/scan-runs/run-1/stop", json={"expected_revision": 1}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_REVISION"


def test_target_route_security_inventory_is_complete() -> None:
    paths = {
        route.path
        for route in router.routes
        if getattr(route, "methods", set()) & {"GET", "POST"}
    }
    assert paths == {
        "/library/activity",
        "/library/activity/stream",
        "/library/operations/stream",
        "/library/identification/pause",
        "/library/identification/resume",
        "/library/scan-runs",
        "/library/scan-runs/current",
        "/library/scan-runs/estimate",
        "/library/scan-runs/{run_id}",
        "/library/scan-runs/{run_id}/pause",
        "/library/scan-runs/{run_id}/resume",
        "/library/scan-runs/{run_id}/stop",
        "/library/scan/start",
        "/library/scan/cancel",
        "/library/scan/status",
    }


def test_legacy_scan_status_projects_the_legacy_contract(
    admin_client, coordinator: AsyncMock
) -> None:
    coordinator.current.return_value = [
        SimpleNamespace(id="run-1", started_at=10.0, updated_at=12.0, state="indexing")
    ]
    coordinator.snapshot.return_value = SimpleNamespace(
        counters={
            "total_count": 10,
            "inspected_count": 6,
            "indexed_count": 3,
            "unchanged_count": 2,
            "errored_count": 1,
        }
    )

    response = admin_client.get("/library/scan/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "scanning",
        "total_files": 10,
        "processed_files": 6,
        "matched_files": 5,
        "failed_files": 1,
        "started_at": 10.0,
        "updated_at": 12.0,
    }


@pytest.mark.asyncio
async def test_activity_stream_coalesces_revisions_and_sends_bounded_heartbeats() -> (
    None
):
    identification = AsyncMock()
    revisions = {"scan": 1, "identification": 2, "operation": 3}
    identification.stream_revisions.side_effect = lambda: dict(revisions)
    delays: list[float] = []

    async def no_wait(delay: float) -> None:
        delays.append(delay)

    events = activity_events(identification, sleep=no_wait)
    first = await anext(events)
    heartbeat = await anext(events)
    revisions["identification"] = 4
    changed = await anext(events)
    await events.aclose()

    assert "event: activity.changed" in first
    assert '"scan":1' in first
    assert heartbeat == ": keepalive\n\n"
    assert '"identification":4' in changed
    assert first.splitlines()[0] != changed.splitlines()[0]
    assert delays == [2.0] * 16
