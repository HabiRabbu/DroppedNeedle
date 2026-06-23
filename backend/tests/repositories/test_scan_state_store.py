"""Task 011: ScanStateStore — singleton state + scan_progress resume ledger."""

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.scan_state_store import ScanStateStore


@pytest.fixture
def store(tmp_path: Path) -> ScanStateStore:
    return ScanStateStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())


@pytest.mark.asyncio
async def test_default_state_is_idle(store):
    state = await store.get_state()
    assert state["status"] == "idle"
    assert state["processed_files"] == 0


@pytest.mark.asyncio
async def test_scan_state_singleton_check(store, tmp_path):
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("INSERT INTO scan_state DEFAULT VALUES")  # id defaults to 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO scan_state DEFAULT VALUES")  # second row blocked
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_start_sets_scanning_and_clears_ledger(store):
    await store.advance(["/old.flac"], processed=1, matched=1, failed=0)
    await store.start(total_files=42)
    state = await store.get_state()
    assert state["status"] == "scanning"
    assert state["total_files"] == 42
    assert state["processed_files"] == 0
    assert await store.load_processed() == set()  # ledger cleared on start


@pytest.mark.asyncio
async def test_advance_appends_ledger_and_updates_counters(store):
    await store.start(total_files=3)
    await store.advance(["/a.flac", "/b.flac"], processed=2, matched=2, failed=0)
    assert await store.load_processed() == {"/a.flac", "/b.flac"}
    assert await store.is_processed("/a.flac") is True
    assert await store.is_processed("/z.flac") is False
    state = await store.get_state()
    assert state["processed_files"] == 2
    assert state["matched_files"] == 2


@pytest.mark.asyncio
async def test_complete_returns_to_idle_and_clears_ledger(store):
    await store.start()
    await store.advance(["/a.flac"], processed=1, matched=1, failed=0)
    await store.complete(matched=1, failed=0)
    state = await store.get_state()
    assert state["status"] == "idle"
    assert await store.load_processed() == set()


@pytest.mark.asyncio
async def test_cancel_sets_cancelled(store):
    await store.start()
    await store.cancel()
    assert (await store.get_state())["status"] == "cancelled"


@pytest.mark.asyncio
async def test_fail_sets_error_and_keeps_ledger(store):
    await store.start()
    await store.advance(["/a.flac"], processed=1, matched=0, failed=1)
    await store.fail("boom")
    state = await store.get_state()
    assert state["status"] == "error"
    assert await store.load_processed() == {"/a.flac"}  # ledger kept for resume
