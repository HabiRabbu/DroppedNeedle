"""Content-addressed durable storage for library-management artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import BinaryIO, Protocol

from core.exceptions import ConflictError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_management import (
    LibraryManagementBlob,
    LibraryManagementBlobCleanupResult,
    ManagementBlobKind,
)

_COPY_CHUNK_SIZE = 1024 * 1024


class _Digest(Protocol):
    def update(self, value: bytes, /) -> None: ...


class LibraryManagementBlobStore:
    """Publish immutable blobs before registering them in the shared SQLite ledger.

    Filesystem publication and SQLite registration are deliberately separate durable
    steps. A grace-period sweep reconciles files left behind if the process stops
    between them.
    """

    def __init__(self, root: Path, ledger: NativeLibraryStore) -> None:
        self._root = Path(root).resolve()
        self._objects_root = self._root / "objects"
        self._temporary_root = self._root / ".tmp"
        self._ledger = ledger
        self._operation_lock = asyncio.Lock()
        self._objects_root.mkdir(parents=True, exist_ok=True)
        self._temporary_root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    async def add_bytes(
        self,
        content: bytes,
        *,
        kind: ManagementBlobKind,
        created_at: float,
        media_metadata_json: str = "{}",
    ) -> LibraryManagementBlob:
        sha256 = hashlib.sha256(content).hexdigest()
        async with self._operation_lock:
            byte_length = await asyncio.to_thread(self._publish_bytes, content, sha256)
            return await self._register(
                sha256=sha256,
                kind=kind,
                byte_length=byte_length,
                media_metadata_json=media_metadata_json,
                created_at=created_at,
            )

    async def add_file(
        self,
        source: Path,
        *,
        kind: ManagementBlobKind,
        created_at: float,
        media_metadata_json: str = "{}",
    ) -> LibraryManagementBlob:
        async with self._operation_lock:
            sha256, byte_length = await asyncio.to_thread(
                self._publish_source_file, Path(source)
            )
            return await self._register(
                sha256=sha256,
                kind=kind,
                byte_length=byte_length,
                media_metadata_json=media_metadata_json,
                created_at=created_at,
            )

    async def read_bytes(self, sha256: str) -> bytes:
        async with self._operation_lock:
            blob = await self._ledger.get_management_blob(sha256)
            if blob is None:
                raise ValidationError("Management blob not found.")
            return await asyncio.to_thread(self._read_verified, blob)

    async def resolve_verified_path(self, sha256: str) -> Path:
        async with self._operation_lock:
            blob = await self._ledger.get_management_blob(sha256)
            if blob is None:
                raise ValidationError("Management blob not found.")
            return await asyncio.to_thread(self._verify_blob_path, blob)

    async def cleanup(
        self,
        *,
        older_than: float,
        limit: int = 500,
    ) -> LibraryManagementBlobCleanupResult:
        if limit < 1 or limit > 500:
            raise ValidationError("Blob cleanup limit is out of range.")
        async with self._operation_lock:
            temporary_removed = await asyncio.to_thread(
                self._remove_old_temporary_files, older_than, limit
            )
            remaining = limit - temporary_removed
            ledger_removed = 0
            if remaining > 0:
                ledger_removed = await self._remove_unreferenced_ledger_blobs(
                    older_than=older_than, limit=remaining
                )
            remaining -= ledger_removed
            unledgered_removed = 0
            if remaining > 0:
                candidates = await asyncio.to_thread(
                    self._find_old_object_candidates, older_than, remaining
                )
                for sha256, path in candidates:
                    if await self._ledger.get_management_blob(sha256) is not None:
                        continue
                    await asyncio.to_thread(self._unlink_object, path)
                    unledgered_removed += 1
            return LibraryManagementBlobCleanupResult(
                temporary_files_removed=temporary_removed,
                unreferenced_blobs_removed=ledger_removed,
                unledgered_files_removed=unledgered_removed,
            )

    async def _register(
        self,
        *,
        sha256: str,
        kind: ManagementBlobKind,
        byte_length: int,
        media_metadata_json: str,
        created_at: float,
    ) -> LibraryManagementBlob:
        return await self._ledger.register_management_blob(
            LibraryManagementBlob(
                sha256=sha256,
                kind=kind,
                byte_length=byte_length,
                relative_path=self._relative_path(sha256).as_posix(),
                media_metadata_json=media_metadata_json,
                created_at=created_at,
            )
        )

    def _publish_bytes(self, content: bytes, sha256: str) -> int:
        temporary_path = self._new_temporary_path()
        try:
            with temporary_path.open("wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            self._publish_temporary(temporary_path, sha256, len(content))
            return len(content)
        finally:
            self._remove_temporary(temporary_path)

    def _publish_source_file(self, source: Path) -> tuple[str, int]:
        if not source.is_file() or source.is_symlink():
            raise ValidationError("The blob source must be a regular file.")
        temporary_path = self._new_temporary_path()
        digest = hashlib.sha256()
        byte_length = 0
        try:
            with source.open("rb") as input_file, temporary_path.open("wb") as output:
                byte_length = self._copy_and_hash(input_file, output, digest)
                output.flush()
                os.fsync(output.fileno())
            sha256 = digest.hexdigest()
            self._publish_temporary(temporary_path, sha256, byte_length)
            return sha256, byte_length
        finally:
            self._remove_temporary(temporary_path)

    @staticmethod
    def _copy_and_hash(input_file: BinaryIO, output: BinaryIO, digest: _Digest) -> int:
        byte_length = 0
        while chunk := input_file.read(_COPY_CHUNK_SIZE):
            output.write(chunk)
            digest.update(chunk)
            byte_length += len(chunk)
        return byte_length

    def _publish_temporary(
        self, temporary_path: Path, sha256: str, byte_length: int
    ) -> None:
        temporary_hash, temporary_length = self._hash_file(temporary_path)
        if temporary_hash != sha256 or temporary_length != byte_length:
            raise ConflictError("The staged management blob failed validation.")
        destination = self._path_for_hash(sha256)
        self._reject_symlink_components(destination.parent)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._reject_symlink_components(destination)
        try:
            os.link(temporary_path, destination)
            self._fsync_directory(destination.parent)
        except FileExistsError:
            existing_hash, existing_length = self._hash_file(destination)
            if existing_hash != sha256 or existing_length != byte_length:
                raise ConflictError(
                    "Existing content-addressed blob bytes do not match their hash."
                )

    def _read_verified(self, blob: LibraryManagementBlob) -> bytes:
        path = self._verify_blob_path(blob)
        content = path.read_bytes()
        if len(content) != blob.byte_length:
            raise ConflictError("Management blob length validation failed.")
        if hashlib.sha256(content).hexdigest() != blob.sha256:
            raise ConflictError("Management blob hash validation failed.")
        return content

    def _verify_blob_path(self, blob: LibraryManagementBlob) -> Path:
        expected = self._relative_path(blob.sha256)
        supplied = Path(blob.relative_path)
        if supplied != expected:
            raise ValidationError("The management blob path is not canonical.")
        path = self._resolve_relative(supplied)
        self._reject_symlink_components(path)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as error:
            raise ConflictError("Management blob bytes are missing.") from error
        if not stat.S_ISREG(mode):
            raise ConflictError("Management blob bytes are not a regular file.")
        file_hash, byte_length = self._hash_file(path)
        if file_hash != blob.sha256 or byte_length != blob.byte_length:
            raise ConflictError("Management blob validation failed.")
        return path

    async def _remove_unreferenced_ledger_blobs(
        self, *, older_than: float, limit: int
    ) -> int:
        candidates = await self._ledger.list_unreferenced_management_blobs(
            older_than=older_than, limit=limit
        )
        removed = 0
        for blob in candidates:
            try:
                relative_path = await self._ledger.delete_unreferenced_management_blob(
                    blob.sha256
                )
            except ConflictError:
                continue
            path = self._resolve_registered_path(blob.sha256, relative_path)
            await asyncio.to_thread(self._unlink_object, path)
            removed += 1
        return removed

    def _remove_old_temporary_files(self, older_than: float, limit: int) -> int:
        removed = 0
        examined = 0
        maximum_examined = limit * 4
        with os.scandir(self._temporary_root) as entries:
            for entry in entries:
                if examined >= maximum_examined or removed >= limit:
                    break
                examined += 1
                try:
                    metadata = entry.stat(follow_symlinks=False)
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or not entry.name.endswith(".tmp")
                        or metadata.st_mtime >= older_than
                    ):
                        continue
                    Path(entry.path).unlink()
                    removed += 1
                except FileNotFoundError:
                    continue
        if removed:
            self._fsync_directory(self._temporary_root)
        return removed

    def _find_old_object_candidates(
        self, older_than: float, limit: int
    ) -> list[tuple[str, Path]]:
        candidates: list[tuple[str, Path]] = []
        examined_directories = 0
        examined_files = 0
        maximum_examined = max(limit * 4, 4)
        for first in self._bounded_directories(self._objects_root, 256):
            for second in self._bounded_directories(first, 256):
                if examined_directories >= maximum_examined:
                    return candidates
                examined_directories += 1
                with os.scandir(second) as entries:
                    for entry in entries:
                        if (
                            len(candidates) >= limit
                            or examined_files >= maximum_examined
                        ):
                            return candidates
                        examined_files += 1
                        try:
                            metadata = entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if (
                            not stat.S_ISREG(metadata.st_mode)
                            or not entry.name.endswith(".blob")
                            or metadata.st_mtime >= older_than
                        ):
                            continue
                        sha256 = entry.name.removesuffix(".blob")
                        if not self._valid_sha256(sha256):
                            continue
                        path = Path(entry.path)
                        if path != self._path_for_hash(sha256):
                            continue
                        candidates.append((sha256, path))
        return candidates

    @staticmethod
    def _bounded_directories(root: Path, limit: int) -> list[Path]:
        if not root.exists():
            return []
        directories: list[Path] = []
        with os.scandir(root) as entries:
            for entry in entries:
                if len(directories) >= limit:
                    break
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
        directories.sort(key=lambda path: path.name)
        return directories

    def _unlink_object(self, path: Path) -> None:
        self._reject_symlink_components(path)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        self._fsync_directory(path.parent)

    def _new_temporary_path(self) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="management-", suffix=".tmp", dir=self._temporary_root
        )
        os.close(descriptor)
        return Path(raw_path)

    def _remove_temporary(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        self._fsync_directory(self._temporary_root)

    def _path_for_hash(self, sha256: str) -> Path:
        if not self._valid_sha256(sha256):
            raise ValidationError("Invalid management blob hash.")
        return self._resolve_relative(self._relative_path(sha256))

    def _resolve_registered_path(self, sha256: str, relative_path: str) -> Path:
        supplied = Path(relative_path)
        if supplied != self._relative_path(sha256):
            raise ValidationError("The management blob path is not canonical.")
        return self._resolve_relative(supplied)

    def _resolve_relative(self, relative_path: Path) -> Path:
        if relative_path.is_absolute() or any(
            part in {"", ".", ".."} for part in relative_path.parts
        ):
            raise ValidationError("Invalid management blob path.")
        candidate = self._root / relative_path
        self._reject_symlink_components(candidate)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise ValidationError("Management blob path escapes its storage root.")
        return resolved

    def _reject_symlink_components(self, path: Path) -> None:
        if not path.is_relative_to(self._root):
            raise ValidationError("Management blob path escapes its storage root.")
        current = self._root
        for part in path.relative_to(self._root).parts:
            current /= part
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise ValidationError(
                        "Management blob paths cannot contain symbolic links."
                    )
            except FileNotFoundError:
                continue

    @staticmethod
    def _relative_path(sha256: str) -> Path:
        if not LibraryManagementBlobStore._valid_sha256(sha256):
            raise ValidationError("Invalid management blob hash.")
        return Path("objects", sha256[:2], sha256[2:4], f"{sha256}.blob")

    @staticmethod
    def _valid_sha256(value: str) -> bool:
        return (
            len(value) == 64
            and value == value.lower()
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        byte_length = 0
        try:
            with path.open("rb") as input_file:
                while chunk := input_file.read(_COPY_CHUNK_SIZE):
                    digest.update(chunk)
                    byte_length += len(chunk)
        except OSError as error:
            raise ConflictError("Management blob bytes could not be read.") from error
        return digest.hexdigest(), byte_length

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
