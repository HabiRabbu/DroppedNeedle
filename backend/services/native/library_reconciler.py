"""Reconcile missing and excluded target rows from completed inventory."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_work import ScanScope
from services.native.library_filesystem_coordinator import LibraryFilesystemCoordinator

RECONCILIATION_BATCH_SIZE = 256


class LibraryReconciler:
    def __init__(
        self,
        store: NativeLibraryStore,
        filesystem_coordinator: LibraryFilesystemCoordinator | None = None,
    ) -> None:
        self._store = store
        self._filesystem = filesystem_coordinator

    async def reconcile(
        self,
        run_id: str,
        scopes: list[ScanScope],
        checkpoint: Callable[[str, str], Awaitable[bool]] | None = None,
    ) -> dict[str, int]:
        totals = {
            "missing": 0,
            "excluded": 0,
            "restored": 0,
            "identification_enqueued": 0,
            "reviews_resolved": 0,
        }
        for scope in scopes:
            while True:
                if checkpoint is not None and not await checkpoint(
                    run_id, scope.policy_revision
                ):
                    return totals
                if self._filesystem is None:
                    result = await self._store.reconcile_scan_scope_batch(
                        run_id,
                        scope.root_id,
                        scope.relative_path,
                        now=time.time(),
                        limit=RECONCILIATION_BATCH_SIZE,
                    )
                else:
                    async with self._filesystem.read(scope.root_id):
                        allow_missing = self._filesystem.scan_revision(
                            run_id, scope.root_id
                        ) == self._filesystem.revision(scope.root_id)
                        result = await self._store.reconcile_scan_scope_batch(
                            run_id,
                            scope.root_id,
                            scope.relative_path,
                            now=time.time(),
                            limit=RECONCILIATION_BATCH_SIZE,
                            allow_missing=allow_missing,
                        )
                for key in totals:
                    totals[key] += int(result[key])
                if result["done"]:
                    break
        return totals
