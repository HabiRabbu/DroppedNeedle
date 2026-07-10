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
    await store.update("t1", status=FreeMusicStatus.DOWNLOADING, files_total=10, identifier="x")
    await store.update("t1", bytes_downloaded=512)

    task = await store.get("t1")
    assert task.status == FreeMusicStatus.DOWNLOADING
    assert task.files_total == 10  # not clobbered by the second update
    assert task.identifier == "x"
    assert task.bytes_downloaded == 512


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
