import asyncio
import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from core.exceptions import ConflictError, ValidationError
from infrastructure.library_management_blob_store import LibraryManagementBlobStore
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_management import (
    LibraryManagementBlob,
    LibraryManagementBlobReference,
)


@pytest.fixture
def ledger(tmp_path: Path) -> NativeLibraryStore:
    database = tmp_path / "library.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
    return NativeLibraryStore(database, threading.Lock())


@pytest.fixture
def blob_store(
    tmp_path: Path, ledger: NativeLibraryStore
) -> LibraryManagementBlobStore:
    return LibraryManagementBlobStore(tmp_path / "management-blobs", ledger)


@pytest.mark.asyncio
async def test_duplicate_content_reuses_one_verified_blob(
    blob_store: LibraryManagementBlobStore, ledger: NativeLibraryStore
) -> None:
    first = await blob_store.add_bytes(
        b"semantic snapshot", kind="tag_snapshot", created_at=1
    )
    second = await blob_store.add_bytes(
        b"semantic snapshot", kind="tag_snapshot", created_at=2
    )

    assert first.sha256 == second.sha256
    assert first.relative_path == second.relative_path
    assert await blob_store.read_bytes(first.sha256) == b"semantic snapshot"
    with sqlite3.connect(ledger.db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM library_management_blobs"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.asyncio
async def test_concurrent_publishers_deduplicate_without_overwriting(
    tmp_path: Path, ledger: NativeLibraryStore
) -> None:
    root = tmp_path / "management-blobs"
    first_store = LibraryManagementBlobStore(root, ledger)
    second_store = LibraryManagementBlobStore(root, ledger)

    first, second = await asyncio.gather(
        first_store.add_bytes(b"shared", kind="image", created_at=1),
        second_store.add_bytes(b"shared", kind="image", created_at=1),
    )

    assert first.sha256 == second.sha256
    assert await first_store.read_bytes(first.sha256) == b"shared"
    assert len(list((root / "objects").glob("*/*/*.blob"))) == 1


@pytest.mark.asyncio
async def test_file_publish_streams_and_verifies_source(
    tmp_path: Path, blob_store: LibraryManagementBlobStore
) -> None:
    source = tmp_path / "snapshot.bin"
    source.write_bytes(b"snapshot from file")

    blob = await blob_store.add_file(source, kind="sidecar_manifest", created_at=1)

    assert blob.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert await blob_store.read_bytes(blob.sha256) == source.read_bytes()


@pytest.mark.asyncio
async def test_noncanonical_and_symlink_paths_are_rejected(
    tmp_path: Path, ledger: NativeLibraryStore, blob_store: LibraryManagementBlobStore
) -> None:
    await ledger.register_management_blob(
        LibraryManagementBlob(
            sha256="a" * 64,
            kind="image",
            byte_length=1,
            relative_path="../outside",
            created_at=1,
        )
    )
    with pytest.raises(ValidationError):
        await blob_store.read_bytes("a" * 64)

    content = b"symlink escape"
    digest = hashlib.sha256(content).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    first_fanout = blob_store.root / "objects" / digest[:2]
    first_fanout.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        await blob_store.add_bytes(content, kind="image", created_at=2)
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_corrupt_or_mismatched_blob_is_never_reused(
    blob_store: LibraryManagementBlobStore,
) -> None:
    content = b"expected bytes"
    blob = await blob_store.add_bytes(content, kind="image", created_at=1)
    path = await blob_store.resolve_verified_path(blob.sha256)
    path.write_bytes(b"corrupted data")

    with pytest.raises(ConflictError):
        await blob_store.read_bytes(blob.sha256)
    with pytest.raises(ConflictError):
        await blob_store.add_bytes(content, kind="image", created_at=2)


@pytest.mark.asyncio
async def test_cleanup_is_bounded_and_respects_grace_and_references(
    blob_store: LibraryManagementBlobStore, ledger: NativeLibraryStore
) -> None:
    old_time = time.time() - 100
    temporary = blob_store.root / ".tmp" / "interrupted.tmp"
    temporary.write_bytes(b"partial")
    os.utime(temporary, (old_time, old_time))

    unreferenced = await blob_store.add_bytes(
        b"unreferenced", kind="image", created_at=old_time
    )
    referenced = await blob_store.add_bytes(
        b"referenced", kind="image", created_at=old_time
    )
    await ledger.add_management_blob_reference(
        LibraryManagementBlobReference(
            blob_sha256=referenced.sha256,
            reference_kind="artwork",
            reference_id="album-1",
            created_at=old_time,
        )
    )

    orphan_content = b"published before ledger registration"
    orphan_hash = hashlib.sha256(orphan_content).hexdigest()
    orphan_path = (
        blob_store.root
        / "objects"
        / orphan_hash[:2]
        / orphan_hash[2:4]
        / f"{orphan_hash}.blob"
    )
    orphan_path.parent.mkdir(parents=True)
    orphan_path.write_bytes(orphan_content)
    os.utime(orphan_path, (old_time, old_time))

    result = await blob_store.cleanup(older_than=time.time() - 10, limit=10)

    assert result.temporary_files_removed == 1
    assert result.unreferenced_blobs_removed == 1
    assert result.unledgered_files_removed == 1
    assert not temporary.exists()
    assert await ledger.get_management_blob(unreferenced.sha256) is None
    assert not orphan_path.exists()
    assert await blob_store.read_bytes(referenced.sha256) == b"referenced"


@pytest.mark.asyncio
async def test_cleanup_refuses_invalid_limit(
    blob_store: LibraryManagementBlobStore,
) -> None:
    with pytest.raises(ValidationError):
        await blob_store.cleanup(older_than=0, limit=501)
