import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_management import LibraryManagementExternalRefreshDelivery


def _store(tmp_path: Path) -> tuple[NativeLibraryStore, Path]:
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
    store = NativeLibraryStore(path, threading.Lock())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO library_operation_jobs "
            "(id,kind,state,created_at,updated_at) "
            "VALUES ('operation-1','library_management','succeeded',1,1)"
        )
    return store, path


def _delivery(**overrides) -> LibraryManagementExternalRefreshDelivery:
    values = {
        "id": "delivery-1",
        "operation_job_id": "operation-1",
        "target": "jellyfin",
        "max_attempts": 2,
        "retry_delay_seconds": 30,
        "created_at": 10.0,
        "updated_at": 10.0,
    }
    values.update(overrides)
    return LibraryManagementExternalRefreshDelivery(**values)


def test_external_refresh_schema_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")

    NativeLibraryStore(path, threading.Lock())
    NativeLibraryStore(path, threading.Lock())

    with sqlite3.connect(path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='library_management_external_refresh_deliveries'"
        ).fetchone()
    assert table is not None


@pytest.mark.asyncio
async def test_external_refresh_delivery_is_deduped_and_retried(
    tmp_path: Path,
) -> None:
    store, _path = _store(tmp_path)

    inserted, created = await store.ensure_library_management_external_refresh(
        _delivery()
    )
    repeated, repeated_created = await store.ensure_library_management_external_refresh(
        _delivery(id="another-id")
    )
    assert created is True
    assert repeated_created is False
    assert repeated.id == inserted.id

    claimed = await store.claim_library_management_external_refresh(
        "worker-1", now=10.0, lease_seconds=60
    )
    assert claimed is not None
    assert claimed.state == "delivering"
    assert claimed.attempts == 1

    retry = await store.finish_library_management_external_refresh(
        claimed.id,
        "worker-1",
        succeeded=False,
        retryable=True,
        failure_code="EXTERNAL_REFRESH_FAILED",
        now=10.0,
    )
    assert retry.state == "retry_wait"
    assert retry.not_before == 40.0
    assert (
        await store.claim_library_management_external_refresh(
            "worker-1", now=39.0, lease_seconds=60
        )
        is None
    )

    claimed_again = await store.claim_library_management_external_refresh(
        "worker-1", now=40.0, lease_seconds=60
    )
    assert claimed_again is not None
    assert claimed_again.attempts == 2
    completed = await store.finish_library_management_external_refresh(
        claimed_again.id,
        "worker-1",
        succeeded=True,
        retryable=False,
        failure_code=None,
        now=40.0,
    )
    assert completed.state == "succeeded"
    assert completed.completed_at == 40.0
    parent = await store.get_operation_job("operation-1")
    assert parent is not None
    assert parent["state"] == "succeeded"


@pytest.mark.asyncio
async def test_expired_final_delivery_lease_recovers_as_failed(tmp_path: Path) -> None:
    store, _path = _store(tmp_path)
    await store.ensure_library_management_external_refresh(_delivery(max_attempts=1))
    claimed = await store.claim_library_management_external_refresh(
        "worker-1", now=10.0, lease_seconds=60
    )
    assert claimed is not None

    assert (
        await store.recover_expired_library_management_external_refreshes(now=70.0) == 1
    )
    rows = await store.list_library_management_external_refreshes("operation-1")
    assert rows[0].state == "failed"
    assert rows[0].failure_code == "EXTERNAL_REFRESH_INTERRUPTED"
