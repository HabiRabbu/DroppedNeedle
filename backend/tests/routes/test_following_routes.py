"""Following hub read routes (Phase 6)."""

import asyncio
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from api.v1.routes.following import router as following_router
from core.dependencies import get_follow_service
from infrastructure.persistence.follow_store import FollowStore, NewReleaseInput
from services.follow_service import FollowService
from tests.helpers import build_test_client, override_user_auth

ARTIST = "AAAAAAAA-1111-2222-3333-444444444444"
ARTIST_LOWER = ARTIST.lower()


def _run(coro):
    return asyncio.run(coro)


def _seed(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users "
            "(id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user')"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, display_name, role) VALUES (?, ?, ?)",
            [("user-a", "Alice", "user"), ("user-b", "Bob", "user")],
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS library_files "
            "(id TEXT PRIMARY KEY, release_group_mbid TEXT, deleted_at REAL)"
        )
        conn.commit()
    finally:
        conn.close()


def _ri(rg: str, title: str, date: str) -> NewReleaseInput:
    return NewReleaseInput(
        release_group_mbid=rg,
        release_group_mbid_lower=rg.lower(),
        artist_mbid_lower=ARTIST_LOWER,
        artist_name="Radiohead",
        title=title,
        primary_type="Album",
        first_release_date=date,
    )


@pytest.fixture
def ctx(tmp_path: Path):
    db = tmp_path / "library.db"
    store = FollowStore(db_path=db, write_lock=threading.Lock())
    _seed(db)
    _run(store.follow_artist("user-a", ARTIST, "Radiohead"))
    _run(store.seed_baseline(ARTIST_LOWER, []))
    _run(
        store.record_new_releases(
            ARTIST_LOWER,
            [
                _ri("RG-NEW", "Wanted Album", "2026-02-01"),
                _ri("RG-OLD", "Older Album", "2025-01-01"),
            ],
            ["rg-new", "rg-old"],
        )
    )
    service = FollowService(store, AsyncMock())
    app = FastAPI()
    app.include_router(following_router)
    app.dependency_overrides[get_follow_service] = lambda: service
    override_user_auth(app, role="user", user_id="user-a")
    return SimpleNamespace(client=build_test_client(app), store=store)


def test_list_followed_artists(ctx):
    resp = ctx.client.get("/following/artists")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["mbid"] == ARTIST
    assert body[0]["name"] == "Radiohead"
    assert body[0]["auto_download"] is False


def test_new_releases_newest_first(ctx):
    resp = ctx.client.get("/following/new-releases")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert [i["title"] for i in body["items"]] == ["Wanted Album", "Older Album"]
    assert body["items"][0]["artist_mbid"] == ARTIST


def test_new_releases_pagination(ctx):
    resp = ctx.client.get("/following/new-releases?limit=1&offset=0")
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Wanted Album"


def test_following_is_per_user(ctx):
    # user-b follows nothing -> empty hub
    app = ctx.client.app
    override_user_auth(app, role="user", user_id="user-b")
    assert ctx.client.get("/following/artists").json() == []
    assert ctx.client.get("/following/new-releases").json()["total"] == 0
