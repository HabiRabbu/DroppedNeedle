"""Per-user Follow + auto-download artist routes (Phase 2)."""

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from api.v1.routes.artists import router as artists_router
from core.dependencies import get_follow_service
from infrastructure.persistence.follow_store import FollowStore
from services.follow_service import FollowService
from tests.helpers import build_test_client, override_user_auth

VALID_MBID = "11111111-2222-3333-4444-555555555555"


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users "
            "(id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user')"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, display_name, role) VALUES (?, ?, ?)",
            [("user-a", "Alice", "user"), ("user-b", "Bob", "user"), ("admin-1", "Admin", "admin")],
        )
        conn.commit()
    finally:
        conn.close()


def _make_app(db_path: Path, *, role: str = "user", user_id: str = "user-a"):
    """A FastAPI app for the artists router with a real FollowStore over db_path
    (shared file) and a chosen authenticated user."""
    store = FollowStore(db_path=db_path, write_lock=threading.Lock())
    mb_repo = AsyncMock()
    mb_repo.get_artist_by_id.return_value = {"name": "Radiohead"}
    service = FollowService(store, mb_repo)
    app = FastAPI()
    app.include_router(artists_router)
    app.dependency_overrides[get_follow_service] = lambda: service
    override_user_auth(app, role=role, user_id=user_id)
    return app


@pytest.fixture
def ctx(tmp_path: Path):
    db = tmp_path / "library.db"
    _seed_auth_users(db)
    app = _make_app(db)
    return SimpleNamespace(client=build_test_client(app), db=db)


def test_follow_status_roundtrip(ctx):
    assert ctx.client.get(f"/artists/{VALID_MBID}/follow").json() == {
        "followed": False,
        "auto_download": False,
        "auto_download_state": "none",
    }
    resp = ctx.client.put(f"/artists/{VALID_MBID}/follow", json={"followed": True})
    assert resp.status_code == 200
    assert resp.json()["followed"] is True
    assert ctx.client.get(f"/artists/{VALID_MBID}/follow").json()["followed"] is True

    ctx.client.put(f"/artists/{VALID_MBID}/follow", json={"followed": False})
    assert ctx.client.get(f"/artists/{VALID_MBID}/follow").json()["followed"] is False


def test_invalid_mbid_returns_400(ctx):
    assert ctx.client.get("/artists/not-an-mbid/follow").status_code == 400


def test_auto_download_requires_following(ctx):
    resp = ctx.client.put(f"/artists/{VALID_MBID}/auto-download", json={"enabled": True})
    assert resp.status_code == 400


def test_user_auto_download_is_pending(ctx):
    ctx.client.put(f"/artists/{VALID_MBID}/follow", json={"followed": True})
    resp = ctx.client.put(f"/artists/{VALID_MBID}/auto-download", json={"enabled": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_download"] is True
    assert body["auto_download_state"] == "pending"


def test_admin_auto_download_is_approved(tmp_path: Path):
    db = tmp_path / "library.db"
    _seed_auth_users(db)
    client = build_test_client(_make_app(db, role="admin", user_id="admin-1"))
    client.put(f"/artists/{VALID_MBID}/follow", json={"followed": True})
    resp = client.put(f"/artists/{VALID_MBID}/auto-download", json={"enabled": True})
    assert resp.json()["auto_download_state"] == "approved"


def test_follow_is_per_user(ctx):
    ctx.client.put(f"/artists/{VALID_MBID}/follow", json={"followed": True})
    # a second user over the SAME db must not see user-a's follow
    other = build_test_client(_make_app(ctx.db, role="user", user_id="user-b"))
    assert other.get(f"/artists/{VALID_MBID}/follow").json()["followed"] is False
