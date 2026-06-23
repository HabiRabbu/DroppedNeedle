"""Phase 3 (AMU-T54): per-user playlist ownership, visibility (D4) and redaction.

Drives the 3-user pattern (admin / owner / other) against the REAL PlaylistService +
PlaylistRepository + AuthStore over a shared temp library.db, switching the acting user
via ``override_user_auth``.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from api.v1.routes.playlists import router as playlists_router
from core.dependencies import get_playlist_service
from infrastructure.persistence.auth_store import AuthStore
from repositories.playlist_repository import PlaylistRepository
from services.playlist_service import PlaylistService
from tests.helpers import build_test_client, override_user_auth

ADMIN_ID = "admin-id"
OWNER_ID = "owner-id"
OWNER_NAME = "Olivia Owner"
OTHER_ID = "other-id"


def _track_dict(name="Track One"):
    return {
        "track_name": name,
        "artist_name": "Artist",
        "album_name": "Album",
        "source_type": "local",
    }


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    auth_store = AuthStore(db_path=db_path, write_lock=lock)
    repo = PlaylistRepository(db_path=db_path, write_lock=lock)
    service = PlaylistService(repo=repo, cache_dir=tmp_path, auth_store=auth_store)
    return SimpleNamespace(auth_store=auth_store, repo=repo, service=service)


async def _seed_users(auth_store):
    # admin created first so get_first_admin() (ORDER BY created_at ASC) returns it.
    await auth_store.create_user(id=ADMIN_ID, display_name="The Admin", role="admin", username="admin")
    await auth_store.create_user(id=OWNER_ID, display_name=OWNER_NAME, role="user", username="owner")
    await auth_store.create_user(id=OTHER_ID, display_name="Otto Other", role="user", username="other")


def _client(env, *, role, user_id):
    app = FastAPI()
    app.include_router(playlists_router)
    app.dependency_overrides[get_playlist_service] = lambda: env.service
    override_user_auth(app, role=role, user_id=user_id)
    return build_test_client(app)


@pytest.mark.asyncio
async def test_owner_creates_views_and_mutates(env):
    await _seed_users(env.auth_store)
    owner = _client(env, role="user", user_id=OWNER_ID)

    created = owner.post("/playlists", json={"name": "Road Trip"})
    assert created.status_code == 201
    body = created.json()
    pid = body["id"]
    assert body["is_owner"] is True
    assert body["is_public"] is False
    assert body["is_redacted"] is False

    detail = owner.get(f"/playlists/{pid}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Road Trip"
    assert detail.json()["is_owner"] is True

    renamed = owner.put(f"/playlists/{pid}", json={"name": "Road Trip v2"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Road Trip v2"

    shared = owner.patch(f"/playlists/{pid}/share", json={"is_public": True})
    assert shared.status_code == 200
    assert shared.json()["is_public"] is True

    assert owner.delete(f"/playlists/{pid}").status_code == 200


@pytest.mark.asyncio
async def test_share_response_includes_real_track_count(env):
    await _seed_users(env.auth_store)
    pl = await env.service.create_playlist("Tunes", user_id=OWNER_ID)
    env.repo.add_tracks(pl.id, [_track_dict("a"), _track_dict("b")])
    owner = _client(env, role="user", user_id=OWNER_ID)

    r = owner.patch(f"/playlists/{pl.id}/share", json={"is_public": True})
    assert r.status_code == 200
    assert r.json()["is_public"] is True
    assert r.json()["track_count"] == 2
    assert r.json()["is_owner"] is True


@pytest.mark.asyncio
async def test_private_playlist_invisible_to_other(env):
    await _seed_users(env.auth_store)
    pl = await env.service.create_playlist("Secret", user_id=OWNER_ID)
    other = _client(env, role="user", user_id=OTHER_ID)

    listing = other.get("/playlists")
    assert listing.status_code == 200
    assert all(p["id"] != pl.id for p in listing.json()["playlists"])

    # Direct GET must 404 (not 403) so existence is not leaked.
    assert other.get(f"/playlists/{pl.id}").status_code == 404

    # Mutations are forbidden.
    assert other.put(f"/playlists/{pl.id}", json={"name": "x"}).status_code == 403
    assert other.delete(f"/playlists/{pl.id}").status_code == 403
    assert other.patch(f"/playlists/{pl.id}/share", json={"is_public": True}).status_code == 403
    assert other.post(f"/playlists/{pl.id}/tracks", json={"tracks": [_track_dict()]}).status_code == 403


@pytest.mark.asyncio
async def test_public_playlist_readonly_with_attribution(env):
    await _seed_users(env.auth_store)
    pl = await env.service.create_playlist("Mixtape", user_id=OWNER_ID)
    owner = _client(env, role="user", user_id=OWNER_ID)
    assert owner.patch(f"/playlists/{pl.id}/share", json={"is_public": True}).status_code == 200

    other = _client(env, role="user", user_id=OTHER_ID)
    listing = other.get("/playlists").json()["playlists"]
    card = next(p for p in listing if p["id"] == pl.id)
    assert card["is_owner"] is False
    assert card["owner_name"] == OWNER_NAME
    assert card["is_redacted"] is False

    detail = other.get(f"/playlists/{pl.id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Mixtape"
    assert detail.json()["is_owner"] is False
    assert detail.json()["owner_name"] == OWNER_NAME

    # Still read-only for the non-owner.
    assert other.put(f"/playlists/{pl.id}", json={"name": "x"}).status_code == 403
    assert other.patch(f"/playlists/{pl.id}/share", json={"is_public": False}).status_code == 403


@pytest.mark.asyncio
async def test_admin_sees_private_redacted(env):
    await _seed_users(env.auth_store)
    pl = await env.service.create_playlist("Olivia's Diary", user_id=OWNER_ID)
    env.repo.add_tracks(pl.id, [_track_dict("a"), _track_dict("b")])
    admin = _client(env, role="admin", user_id=ADMIN_ID)

    row = next(p for p in admin.get("/playlists").json()["playlists"] if p["id"] == pl.id)
    assert row["is_redacted"] is True
    assert row["track_count"] == 2
    assert row["owner_name"] == OWNER_NAME
    assert "name" not in row
    assert "cover_urls" not in row

    detail = admin.get(f"/playlists/{pl.id}")
    assert detail.status_code == 200  # redacted body, not 403
    assert detail.json()["is_redacted"] is True
    assert detail.json()["track_count"] == 2
    assert detail.json()["owner_name"] == OWNER_NAME
    assert "name" not in detail.json()
    assert "tracks" not in detail.json()

    # Admin may not mutate, but may delete for cleanup.
    assert admin.put(f"/playlists/{pl.id}", json={"name": "x"}).status_code == 403
    assert admin.patch(f"/playlists/{pl.id}/share", json={"is_public": True}).status_code == 403
    assert admin.delete(f"/playlists/{pl.id}").status_code == 200


@pytest.mark.asyncio
async def test_private_cover_not_fetchable_by_non_owner(env):
    await _seed_users(env.auth_store)
    pl = await env.service.create_playlist("Secret", user_id=OWNER_ID)
    other = _client(env, role="user", user_id=OTHER_ID)
    admin = _client(env, role="admin", user_id=ADMIN_ID)
    assert other.get(f"/playlists/{pl.id}/cover").status_code == 404
    assert admin.get(f"/playlists/{pl.id}/cover").status_code == 404


@pytest.mark.asyncio
async def test_two_users_import_same_source_ref(env):
    await _seed_users(env.auth_store)
    p1 = await env.service.create_playlist("JF", source_ref="jellyfin:123", user_id=OWNER_ID)
    p2 = await env.service.create_playlist("JF", source_ref="jellyfin:123", user_id=OTHER_ID)
    assert p1.id != p2.id  # the per-user unique index allows both

    assert await env.service.get_imported_source_ids("jellyfin:", user_id=OWNER_ID) == {"123"}
    assert await env.service.get_imported_source_ids("jellyfin:", user_id=OTHER_ID) == {"123"}
    assert (await env.service.get_by_source_ref("jellyfin:123", user_id=OWNER_ID)).id == p1.id
    assert (await env.service.get_by_source_ref("jellyfin:123", user_id=OTHER_ID)).id == p2.id

    # A second import of the SAME source by the SAME user collides on the index.
    with pytest.raises(Exception):
        await env.service.create_playlist("JF dup", source_ref="jellyfin:123", user_id=OWNER_ID)


@pytest.mark.asyncio
async def test_check_track_membership_scoped_to_user(env):
    await _seed_users(env.auth_store)
    owner_pl = await env.service.create_playlist("Owner", user_id=OWNER_ID)
    other_pl = await env.service.create_playlist("Other", user_id=OTHER_ID)
    env.repo.add_tracks(owner_pl.id, [_track_dict("Shared Song")])
    env.repo.add_tracks(other_pl.id, [_track_dict("Shared Song")])

    membership = await env.service.check_track_membership(
        [("Shared Song", "Artist", "Album")], user_id=OWNER_ID,
    )
    assert owner_pl.id in membership
    assert other_pl.id not in membership  # never leaks another user's playlist id


@pytest.mark.asyncio
async def test_migrate_playlists_owner_to_admin(env):
    from main import _migrate_playlists_owner_to_admin

    await _seed_users(env.auth_store)
    env.repo.create_playlist("Legacy 1")  # user_id IS NULL
    env.repo.create_playlist("Legacy 2")

    await _migrate_playlists_owner_to_admin(env.auth_store, env.repo)
    rows = env.repo.get_all_playlists()
    assert rows, "expected backfilled rows"
    assert all(r.user_id == ADMIN_ID for r in rows)
    assert all(r.is_public is False for r in rows)

    # Idempotent: a second run touches nothing.
    assert env.repo.assign_unowned_to(ADMIN_ID) == 0


@pytest.mark.asyncio
async def test_delete_user_cascades_playlists(env):
    await _seed_users(env.auth_store)
    pl = await env.service.create_playlist("Owned", user_id=OWNER_ID)
    env.repo.add_tracks(pl.id, [_track_dict()])
    assert env.repo.get_playlist(pl.id) is not None
    assert len(env.repo.get_tracks(pl.id)) == 1

    assert await env.auth_store.delete_user(OWNER_ID) is True

    assert env.repo.get_playlist(pl.id) is None
    assert env.repo.get_tracks(pl.id) == []


def test_playlist_repo_uses_shared_persistence_lock():
    from core.config import get_settings
    from core.dependencies.cache_providers import get_persistence_write_lock
    from core.dependencies.repo_providers import get_playlist_repository

    # The singleton repo opens the real (test-temp) library.db on construction.
    get_settings().library_db_path.parent.mkdir(parents=True, exist_ok=True)
    repo = get_playlist_repository()
    assert repo._write_lock is get_persistence_write_lock()
