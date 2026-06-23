import threading

import pytest

from infrastructure.persistence.request_history import RequestHistoryStore


def test_download_task_id_column_present_nullable_and_no_lidarr_album_id(tmp_path):
    store = RequestHistoryStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())
    conn = store._connect()
    try:
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(request_history)").fetchall()}
    finally:
        conn.close()

    assert "download_task_id" in cols
    # PRAGMA table_info "notnull" flag == 0 → column is nullable
    assert cols["download_task_id"]["notnull"] == 0
    assert "lidarr_album_id" not in cols


@pytest.mark.asyncio
async def test_async_update_download_task_id_persists(tmp_path):
    store = RequestHistoryStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())
    await store.async_record_request("RG-1", "Artist", "Album", user_id="u1")

    # column starts unset
    record = await store.async_get_record("RG-1")
    assert record is not None
    assert record.download_task_id is None

    await store.async_update_download_task_id("RG-1", "task-42")

    record = await store.async_get_record("RG-1")
    assert record is not None
    assert record.download_task_id == "task-42"


@pytest.mark.asyncio
async def test_async_update_download_task_id_is_case_insensitive_on_mbid(tmp_path):
    store = RequestHistoryStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())
    await store.async_record_request("RG-Mixed", "Artist", "Album", user_id="u1")

    # the setter normalizes the mbid (matches async_record_request's lower-casing)
    await store.async_update_download_task_id("rg-mixed", "task-99")

    record = await store.async_get_record("RG-Mixed")
    assert record is not None
    assert record.download_task_id == "task-99"
