"""DownloadStore tests - migrations, task CRUD, ownership scoping, quarantine,
candidates round-trip (AUD-9), the atomic link_picked_candidate (AUD-8), and the
user_id -> auth_users ON DELETE CASCADE foreign key (AUD-6)."""

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.download_store import DownloadStore
from models.download import ScoredCandidate
from repositories.protocols.download_client import DownloadSearchResult


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT, role TEXT)"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, username, role) VALUES (?, ?, ?)",
            [("user-a", "alice", "user"), ("user-b", "bob", "user"), ("admin-1", "root", "admin")],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def store(tmp_path: Path) -> DownloadStore:
    db_path = tmp_path / "library.db"
    s = DownloadStore(db_path=db_path, write_lock=threading.Lock())
    _seed_auth_users(db_path)
    return s


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    DownloadStore(db_path=db_path, write_lock=lock)
    DownloadStore(db_path=db_path, write_lock=lock)  # re-run must not error
    assert db_path.exists()


@pytest.mark.asyncio
async def test_create_task_returns_uuid(store):
    task = await store.create_task(
        user_id="user-a", release_group_mbid="rg-1", artist_name="A", album_title="B"
    )
    assert len(task.id) == 32
    assert task.status == "queued"
    fetched = await store.get_task(task.id)
    assert fetched is not None
    assert fetched.release_group_mbid == "rg-1"


@pytest.mark.asyncio
async def test_get_task_for_user_ownership(store):
    task = await store.create_task(
        user_id="user-a", release_group_mbid="rg", artist_name="A", album_title="B"
    )
    assert await store.get_task_for_user(task.id, "user-a", "user") is not None
    assert await store.get_task_for_user(task.id, "user-b", "user") is None
    assert await store.get_task_for_user(task.id, "admin-1", "admin") is not None


@pytest.mark.asyncio
async def test_active_task_dedup_is_user_scoped(store):
    task = await store.create_task(
        user_id="user-a", download_type="album", release_group_mbid="rg",
        artist_name="A", album_title="B",
    )
    active = await store.get_active_task_for_album("rg", "user-a")
    assert active is not None and active.id == task.id
    assert await store.get_active_task_for_album("rg", "user-b") is None


@pytest.mark.asyncio
async def test_list_tasks_filters_by_release_group(store):
    a1 = await store.create_task(
        user_id="user-a", release_group_mbid="rg-1", artist_name="A", album_title="One"
    )
    await store.create_task(
        user_id="user-a", release_group_mbid="rg-2", artist_name="A", album_title="Two"
    )
    # another user's task for the same release group must not leak to user-a
    await store.create_task(
        user_id="user-b", release_group_mbid="rg-1", artist_name="A", album_title="One"
    )

    rg1 = await store.list_tasks(user_id="user-a", user_role="user", release_group_mbid="rg-1")
    assert [t.id for t in rg1] == [a1.id]

    # admin sees every user's task for the release group
    rg1_admin = await store.list_tasks(
        user_id="admin-1", user_role="admin", release_group_mbid="rg-1"
    )
    assert len(rg1_admin) == 2

    # no release-group filter -> all of user-a's tasks
    all_a = await store.list_tasks(user_id="user-a", user_role="user")
    assert len(all_a) == 2


@pytest.mark.asyncio
async def test_quarantine_set_roundtrip(store):
    await store.record_quarantine("slskd", "peerX", "bad.flac", "verify_failed", "rg")
    quarantine = await store.load_quarantine_set()
    assert ("peerX", "bad.flac") in quarantine
    assert isinstance(quarantine, set)


@pytest.mark.asyncio
async def test_search_job_candidates_roundtrip(store):
    job = await store.create_search_job("user-a", "A", "B", 1997, 12, "rg", "A - B")
    candidates = [
        ScoredCandidate(
            username="u",
            parent_directory="p",
            files=[
                DownloadSearchResult(
                    username="u", filename="f.flac", parent_directory="p", size=1, extension="flac"
                )
            ],
            coherence=0.9,
            file_confidence=0.8,
            final_score=0.85,
            tier="auto",
        )
    ]
    await store.set_search_job_candidates(job.id, candidates)
    out = await store.get_search_job_candidates(job.id)
    assert len(out) == 1
    assert out[0].username == "u"
    assert out[0].tier == "auto"
    assert out[0].files[0].filename == "f.flac"


@pytest.mark.asyncio
async def test_link_picked_candidate_is_atomic(store):
    job = await store.create_search_job("user-a", "A", "B", None, None, "rg", "q")
    task = await store.create_task(
        user_id="user-a", release_group_mbid="rg", artist_name="A", album_title="B"
    )
    await store.link_picked_candidate(task.id, job.id, 0, "alice", "Folder", 0.82)
    linked_task = await store.get_task(task.id)
    assert linked_task.search_job_id == job.id
    assert linked_task.candidate_index == 0
    assert linked_task.source_username == "alice"
    assert linked_task.preflight_score == pytest.approx(0.82)
    job_after = await store.get_search_job(job.id)
    assert job_after.status == "matched"


@pytest.mark.asyncio
async def test_update_search_job_status(store):
    job = await store.create_search_job("user-a", "A", "B", None, None, None, "q")
    assert job.status == "searching"
    await store.update_search_job_status(job.id, "completed")
    assert (await store.get_search_job(job.id)).status == "completed"


@pytest.mark.asyncio
async def test_delete_expired_search_jobs(store, tmp_path: Path):
    old = await store.create_search_job("user-a", "A", "B", None, None, None, "q")
    fresh = await store.create_search_job("user-a", "C", "D", None, None, None, "q2")
    # Backdate the first job well past the 7-day window.
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("UPDATE search_jobs SET created_at = 0 WHERE id = ?", (old.id,))
        conn.commit()
    finally:
        conn.close()
    removed = await store.delete_expired_search_jobs()
    assert removed == 1
    assert await store.get_search_job(old.id) is None
    assert await store.get_search_job(fresh.id) is not None


@pytest.mark.asyncio
async def test_user_delete_cascades_to_tasks(store, tmp_path: Path):
    task = await store.create_task(
        user_id="user-a", release_group_mbid="rg", artist_name="A", album_title="B"
    )
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM auth_users WHERE id = ?", ("user-a",))
        conn.commit()
    finally:
        conn.close()
    assert await store.get_task(task.id) is None


@pytest.mark.asyncio
async def test_create_task_persists_track_duration(store):
    task = await store.create_task(
        user_id="user-a",
        download_type="track",
        release_group_mbid="rg",
        recording_mbid="rec-1",
        artist_name="A",
        album_title="B",
        track_title="T",
        track_count=1,
        track_duration_seconds=212.5,
    )
    got = await store.get_task(task.id)
    assert got is not None
    assert got.track_duration_seconds == 212.5
