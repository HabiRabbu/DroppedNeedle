"""Route tests for the library scan control plane (real scanner wiring).

The scanner itself is mocked (a tiny fake) - its behaviour is covered by
``test_library_scanner``; here we assert the control plane: admin gating, the
start/cancel state machine, status, and the SSE auth gate.
"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException

from api.v1.routes.library_scan import router
from core.exceptions import ResourceNotFoundError, ValidationError
from core.dependencies import (
    get_cache,
    get_library_manager,
    get_library_scanner,
    get_preferences_service,
    get_scan_state_store,
    get_sse_publisher,
)
from core.task_registry import TaskRegistry
from infrastructure.persistence.library_db import LibraryDB
from infrastructure.persistence.scan_state_store import ScanStateStore
from infrastructure.sse_publisher import SSEPublisher
from middleware import _get_current_admin
from services.native.library_manager import LibraryManager
from tests.helpers import build_test_client, override_admin_auth, override_user_auth


class _FakeScanner:
    def __init__(self) -> None:
        self.scanned_with: list | None = None
        self.scanned_force: bool | None = None
        self.cancelled = False

    async def scan(self, library_paths, resume: bool = False, force: bool = False) -> None:
        self.scanned_with = library_paths
        self.scanned_force = force

    def request_cancel(self) -> None:
        self.cancelled = True


class _FakePrefs:
    def get_library_settings_raw(self):
        return SimpleNamespace(library_paths=["/music"])


class _FakeCache:
    def __init__(self) -> None:
        self.cleared: list[str] = []

    async def clear_prefix(self, prefix: str) -> int:
        self.cleared.append(prefix)
        return 0


@pytest.fixture(autouse=True)
def _reset_registry():
    TaskRegistry.get_instance().reset()
    yield
    TaskRegistry.get_instance().reset()


@pytest.fixture
def scan_store(tmp_path):
    lock = threading.Lock()
    db_path = tmp_path / "library.db"
    LibraryDB(db_path=db_path, write_lock=lock)  # create shared library.db
    return ScanStateStore(db_path=db_path, write_lock=lock)


@pytest.fixture
def fake_scanner():
    return _FakeScanner()


@pytest.fixture
def fake_cache():
    return _FakeCache()


@pytest.fixture
def app(tmp_path, scan_store, fake_scanner, fake_cache):
    db = LibraryDB(db_path=tmp_path / "library.db", write_lock=threading.Lock())
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_scan_state_store] = lambda: scan_store
    application.dependency_overrides[get_sse_publisher] = lambda: SSEPublisher()
    application.dependency_overrides[get_library_manager] = lambda: LibraryManager(db)
    application.dependency_overrides[get_library_scanner] = lambda: fake_scanner
    application.dependency_overrides[get_preferences_service] = lambda: _FakePrefs()
    application.dependency_overrides[get_cache] = lambda: fake_cache
    return application


@pytest.fixture
def admin_client(app):
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    return build_test_client(app)


def test_start_scan_returns_202_for_admin(admin_client, fake_scanner):
    resp = admin_client.post("/library/scan/start")
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_start_scan_default_is_not_forced(admin_client, fake_scanner, fake_cache):
    admin_client.post("/library/scan/start")
    assert fake_scanner.scanned_force is False
    assert fake_cache.cleared == []


def test_start_scan_force_clears_mb_cache_and_passes_force(admin_client, fake_scanner, fake_cache):
    resp = admin_client.post("/library/scan/start?force=true")
    assert resp.status_code == 202
    assert fake_scanner.scanned_force is True
    assert len(fake_cache.cleared) > 0  # MB prefixes were invalidated


def test_start_scan_forbidden_for_non_admin(app):
    def reject_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[_get_current_admin] = reject_admin
    override_user_auth(app, role="user")
    client = build_test_client(app)
    assert client.post("/library/scan/start").status_code == 403


def test_start_scan_conflict_when_already_scanning(admin_client, scan_store):
    asyncio.run(scan_store.start())  # seed an in-progress scan
    assert admin_client.post("/library/scan/start").status_code == 409


def test_start_scan_400_when_no_library_paths(app):
    class _EmptyPrefs:
        def get_library_settings_raw(self):
            return SimpleNamespace(library_paths=[])

    app.dependency_overrides[get_preferences_service] = lambda: _EmptyPrefs()
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    client = build_test_client(app)
    assert client.post("/library/scan/start").status_code == 400


def test_cancel_when_not_running_returns_400(admin_client):
    assert admin_client.post("/library/scan/cancel").status_code == 400


def test_cancel_running_scan(admin_client, scan_store, fake_scanner):
    asyncio.run(scan_store.start())
    resp = admin_client.post("/library/scan/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelling"
    assert fake_scanner.cancelled is True


def test_cancel_forbidden_for_non_admin(app):
    def reject_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[_get_current_admin] = reject_admin
    override_user_auth(app, role="user")
    client = build_test_client(app)
    assert client.post("/library/scan/cancel").status_code == 403


def test_scan_status_idle(admin_client):
    resp = admin_client.get("/library/scan/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_unmatched_empty(admin_client):
    resp = admin_client.get("/library/scan/unmatched")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_unmatched_forbidden_for_non_admin(app):
    # The listing exposes on-disk file paths, so it is admin-only (like resolve).
    def reject_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[_get_current_admin] = reject_admin
    client = build_test_client(app)
    assert client.get("/library/scan/unmatched").status_code == 403


def test_scan_status_requires_auth(app):
    client = build_test_client(app)  # no auth override -> 401
    assert client.get("/library/scan/status").status_code == 401


def test_scan_stream_requires_auth(app):
    # The auth dependency runs before the StreamingResponse starts, so this
    # returns 401 without opening the infinite stream. Stream mechanics are
    # covered at the service level (test_sse_publisher) per AUD-14.
    client = build_test_client(app)  # no auth override
    assert client.get("/library/scan/stream").status_code == 401


# -- unmatched resolve route wiring (scanner logic covered in test_library_scanner) --


def test_resolve_unmatched_accept_returns_resolved(app):
    scanner = AsyncMock()
    scanner.resolve_unmatched = AsyncMock(return_value=None)
    app.dependency_overrides[get_library_scanner] = lambda: scanner
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    client = build_test_client(app)
    resp = client.post("/library/scan/unmatched/1/resolve", json={"resolution": "accept"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    scanner.resolve_unmatched.assert_awaited_once_with(1, "accept", None)


def test_resolve_unmatched_reject_passes_resolution(app):
    scanner = AsyncMock()
    scanner.resolve_unmatched = AsyncMock(return_value=None)
    app.dependency_overrides[get_library_scanner] = lambda: scanner
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    client = build_test_client(app)
    resp = client.post(
        "/library/scan/unmatched/7/resolve",
        json={"resolution": "manual_id", "mbid": "rg-123"},
    )
    assert resp.status_code == 200
    scanner.resolve_unmatched.assert_awaited_once_with(7, "manual_id", "rg-123")


def test_resolve_unmatched_unknown_id_returns_404(app):
    scanner = AsyncMock()
    scanner.resolve_unmatched = AsyncMock(side_effect=ResourceNotFoundError("nope"))
    app.dependency_overrides[get_library_scanner] = lambda: scanner
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    client = build_test_client(app)
    resp = client.post("/library/scan/unmatched/99/resolve", json={"resolution": "reject"})
    assert resp.status_code == 404


def test_resolve_unmatched_bad_request_returns_400(app):
    scanner = AsyncMock()
    scanner.resolve_unmatched = AsyncMock(
        side_effect=ValidationError("A MusicBrainz ID is required to accept this file")
    )
    app.dependency_overrides[get_library_scanner] = lambda: scanner
    override_admin_auth(app)
    override_user_auth(app, role="admin")
    client = build_test_client(app)
    resp = client.post("/library/scan/unmatched/1/resolve", json={"resolution": "accept"})
    assert resp.status_code == 400


def test_resolve_unmatched_forbidden_for_non_admin(app):
    def reject_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[_get_current_admin] = reject_admin
    override_user_auth(app, role="user")
    client = build_test_client(app)
    resp = client.post("/library/scan/unmatched/1/resolve", json={"resolution": "reject"})
    assert resp.status_code == 403
