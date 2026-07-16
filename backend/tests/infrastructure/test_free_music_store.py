"""FreeMusicStore: DDL idempotency, CRUD, scoping, stale sweep."""

import threading

import pytest

from infrastructure.persistence.free_music_store import FreeMusicStore
from models.free_music import FreeMusicStatus


@pytest.fixture()
def store(tmp_path):
    return FreeMusicStore(tmp_path / "library.db", threading.Lock())


def test_ensure_tables_is_idempotent(tmp_path):
    lock = threading.Lock()
    FreeMusicStore(tmp_path / "library.db", lock)
    FreeMusicStore(tmp_path / "library.db", lock)  # must not raise


@pytest.mark.asyncio
async def test_create_and_get(store):
    await store.create("t1", "u1", "album", "rg-1", "Brad Sucks", "Guess Who's a Mess")

    task = await store.get("t1")
    assert task is not None
    assert task.status == FreeMusicStatus.SEARCHING
    assert task.kind == "album" and task.mbid == "rg-1"
    assert task.files_total == 0 and task.error is None


@pytest.mark.asyncio
async def test_update_only_touches_supplied_fields(store):
    await store.create("t1", "u1", "album", "rg-1", "A", "B")
    await store.update(
        "t1", status=FreeMusicStatus.DOWNLOADING, files_total=10, identifier="x"
    )
    await store.update("t1", bytes_downloaded=512)

    task = await store.get("t1")
    assert task.status == FreeMusicStatus.DOWNLOADING
    assert task.files_total == 10  # not clobbered by the second update
    assert task.identifier == "x"
    assert task.bytes_downloaded == 512


@pytest.mark.asyncio
async def test_update_can_require_the_current_status(store):
    await store.create("t1", "u1", "album", "rg-1", "A", "B")

    assert await store.update(
        "t1",
        status=FreeMusicStatus.DOWNLOADING,
        expected_statuses=(FreeMusicStatus.SEARCHING,),
    )
    assert not await store.update(
        "t1",
        status=FreeMusicStatus.COMPLETED,
        expected_statuses=(FreeMusicStatus.SEARCHING,),
    )
    assert (await store.get("t1")).status == FreeMusicStatus.DOWNLOADING


@pytest.mark.asyncio
async def test_list_scopes_to_user_unless_all(store):
    await store.create("a", "u1", "album", "rg-1", "A", "B")
    await store.create("b", "u2", "album", "rg-2", "C", "D")

    assert [t.id for t in await store.list_tasks(user_id="u1")] == ["a"]
    assert {t.id for t in await store.list_tasks(user_id=None)} == {"a", "b"}


@pytest.mark.asyncio
async def test_missing_task_is_none(store):
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_fail_stale_only_touches_non_terminal(store):
    await store.create("running", "u1", "album", "rg-1", "A", "B")
    await store.create("done", "u1", "album", "rg-2", "A", "B")
    await store.update("done", status=FreeMusicStatus.COMPLETED)

    changed = await store.fail_stale("Interrupted by a restart")

    assert changed == 1
    assert (await store.get("running")).status == FreeMusicStatus.FAILED
    assert (await store.get("done")).status == FreeMusicStatus.COMPLETED


@pytest.mark.asyncio
async def test_restart_terminal_is_atomic_and_resets_previous_attempt(store):
    await store.create("failed", "u1", "album", "rg-1", "A", "B")
    await store.update(
        "failed",
        status=FreeMusicStatus.FAILED,
        identifier="old-source",
        format="mp3",
        files_total=10,
        files_completed=4,
        bytes_total=1000,
        bytes_downloaded=400,
        attempts=2,
        error="failed",
    )

    assert await store.restart_terminal("failed") is True
    task = await store.get("failed")
    assert task is not None
    assert task.status == FreeMusicStatus.SEARCHING
    assert task.identifier == "" and task.format == ""
    assert task.files_total == 0 and task.files_completed == 0
    assert task.bytes_total == 0 and task.bytes_downloaded == 0
    assert task.attempts == 0 and task.error is None
    assert await store.restart_terminal("failed") is False


@pytest.mark.asyncio
async def test_delete_terminal_refuses_active_tasks(store):
    await store.create("active", "u1", "album", "rg-1", "A", "B")

    assert await store.delete_terminal("active") is None
    assert await store.get("active") is not None


@pytest.mark.asyncio
async def test_delete_terminal_tasks_is_scoped_and_includes_failures(store):
    await store.create("u1-done", "u1", "album", "rg-1", "A", "B")
    await store.create("u1-failed", "u1", "album", "rg-2", "A", "B")
    await store.create("u1-active", "u1", "album", "rg-3", "A", "B")
    await store.create("u2-done", "u2", "album", "rg-4", "A", "B")
    await store.update("u1-done", status=FreeMusicStatus.COMPLETED)
    await store.update("u1-failed", status=FreeMusicStatus.FAILED)
    await store.update("u2-done", status=FreeMusicStatus.COMPLETED)

    removed = await store.delete_terminal_tasks(user_id="u1")

    assert set(removed) == {("u1-done", "u1"), ("u1-failed", "u1")}
    assert await store.get("u1-done") is None
    assert await store.get("u1-failed") is None
    assert await store.get("u1-active") is not None
    assert await store.get("u2-done") is not None
