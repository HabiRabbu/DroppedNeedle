"""Single durable entry point for every inactive target scan trigger."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path

from core.exceptions import StaleRevisionError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_work import (
    ScanControlResult,
    ScanRequest,
    ScanRequestResult,
    ScanRun,
    ScanRunSnapshot,
    ScanScope,
)
from services.native.library_indexer import LibraryIndexer
from services.native.library_inventory_scanner import LibraryInventoryScanner
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_reconciler import LibraryReconciler
from services.native.library_scan_events import LibraryScanEventPublisher

PolicyResolverGetter = Callable[[], LibraryPolicyResolver]


class LibraryScanCoordinator:
    def __init__(
        self,
        store: NativeLibraryStore,
        inventory: LibraryInventoryScanner,
        indexer: LibraryIndexer,
        reconciler: LibraryReconciler,
        resolver_getter: PolicyResolverGetter,
        events: LibraryScanEventPublisher | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._inventory = inventory
        self._indexer = indexer
        self._reconciler = reconciler
        self._resolver_getter = resolver_getter
        self._events = events
        self._clock = clock

    async def request_run(self, request: ScanRequest) -> ScanRequestResult:
        if not request.scopes:
            raise ValidationError("Select at least one library scope.")
        if any(
            scope.policy_revision != request.policy_revision for scope in request.scopes
        ):
            raise StaleRevisionError("The selected library policy has changed.")
        result = await self._store.request_scan_run(
            request, run_id=str(uuid.uuid4()), requested_at=self._clock()
        )
        if self._events is not None and result.disposition != "conflict":
            run = (await self._store.get_scan_run(result.run_id))[0]
            await self._events.publish(run, event="scan.requested")
        return result

    async def snapshot(self, run_id: str) -> ScanRunSnapshot:
        run, scopes, counters = await self._store.get_scan_run(run_id)
        return ScanRunSnapshot(run=run, scopes=scopes, counters=counters)

    async def current(self) -> list[ScanRun]:
        return await self._store.list_current_scan_runs()

    async def estimate(self, scopes: list[ScanScope]) -> tuple[int, float]:
        return await self._store.estimate_scan_scope(scopes), self._clock()

    async def history(self, *, limit: int = 50) -> list[ScanRun]:
        return await self._store.list_scan_history(limit=limit)

    async def latest_filesystem_terminal(self) -> ScanRun | None:
        return await self._store.get_latest_filesystem_scan_terminal()

    async def history_page(
        self, *, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[ScanRun], str | None]:
        before_terminal_at: float | None = None
        before_id: str | None = None
        if cursor is not None:
            try:
                terminal, before_id = cursor.split(":", 1)
                before_terminal_at = float(terminal)
            except (TypeError, ValueError) as exc:
                raise ValidationError("The scan history cursor is invalid.") from exc
        rows = await self._store.list_scan_history(
            limit=limit + 1,
            before_terminal_at=before_terminal_at,
            before_id=before_id,
        )
        items = rows[:limit]
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            next_cursor = f"{last.terminal_at}:{last.id}"
        return items, next_cursor

    async def control(
        self, run_id: str, control: str, expected_revision: int
    ) -> ScanControlResult:
        run, stream_revision = await self._store.request_scan_control(
            run_id,
            control=control,
            expected_revision=expected_revision,
            now=self._clock(),
        )
        if self._events is not None:
            await self._events.publish(run, event="scan.transition")
        return ScanControlResult(
            run_id=run.id,
            state=run.state,
            row_revision=run.row_revision,
            event_revision=run.event_revision,
            stream_revision=stream_revision,
        )

    async def recover(self) -> list[ScanRun]:
        return await self._store.recover_scan_runs(now=self._clock())

    async def checkpoint(self, run_id: str, frozen_policy_revision: str) -> bool:
        run, _, _ = await self._store.get_scan_run(run_id)
        current_policy_revision = self._resolver_getter().policy_revision
        if current_policy_revision != frozen_policy_revision:
            if run.state == "paused":
                await self._store.transition_scan_run(
                    run.id,
                    expected_state="paused",
                    expected_revision=run.row_revision,
                    new_state="superseded_policy_changed",
                    now=self._clock(),
                    terminal_code="SUPERSEDED_POLICY_CHANGED",
                )
            elif run.state in {"discovering", "indexing", "reconciling", "pausing"}:
                await self._store.transition_scan_run(
                    run.id,
                    expected_state=run.state,
                    expected_revision=run.row_revision,
                    new_state="superseded_policy_changed",
                    now=self._clock(),
                    terminal_code="SUPERSEDED_POLICY_CHANGED",
                )
            return False
        if run.state == "pausing":
            await self._store.transition_scan_run(
                run.id,
                expected_state="pausing",
                expected_revision=run.row_revision,
                new_state="paused",
                now=self._clock(),
            )
            return False
        if run.state == "stopping":
            await self._store.transition_scan_run(
                run.id,
                expected_state="stopping",
                expected_revision=run.row_revision,
                new_state="cancelled",
                now=self._clock(),
            )
            return False
        return run.state in {"discovering", "indexing", "reconciling"}

    async def run_once(self, root_paths: dict[str, Path]) -> ScanRun | None:
        run = await self._store.get_resumable_scan_run()
        newly_claimed = run is None
        if run is None:
            run = await self._store.claim_next_scan_run(now=self._clock())
        if run is None:
            return None
        if newly_claimed and self._events is not None:
            await self._events.publish(run, event="scan.transition")
        try:
            return await self._continue_run(run, root_paths)
        except Exception:  # noqa: BLE001 - a crashed worker must leave a terminal durable run
            current, _, _ = await self._store.get_scan_run(run.id)
            if current.state in {"discovering", "indexing", "reconciling"}:
                failed = await self._store.transition_scan_run(
                    current.id,
                    expected_state=current.state,
                    expected_revision=current.row_revision,
                    new_state="failed",
                    now=self._clock(),
                    terminal_code="UNEXPECTED_WORKER_FAILURE",
                )
                if self._events is not None:
                    await self._events.publish(failed, event="scan.transition")
            raise

    async def _continue_run(self, run: ScanRun, root_paths: dict[str, Path]) -> ScanRun:
        run, scopes, _ = await self._store.get_scan_run(run.id)
        frozen_policy_revision = scopes[0].policy_revision
        if run.state == "discovering":
            await self._store.prepare_scan_discovery_resume(run.id)
            run, scopes, _ = await self._store.get_scan_run(run.id)
            run = await self._inventory.discover(
                run,
                scopes,
                root_paths,
                self._resolver_getter(),
                self.checkpoint,
            )
            if self._events is not None:
                await self._events.publish(run, event="scan.progress", counter=True)
            run, scopes, _ = await self._store.get_scan_run(run.id)
            if run.state != "discovering":
                return run
            run = await self._store.transition_scan_run(
                run.id,
                expected_state="discovering",
                expected_revision=run.row_revision,
                new_state="indexing",
                now=self._clock(),
            )
            if self._events is not None:
                await self._events.publish(run, event="scan.transition")

        if run.state == "indexing":
            if not await self.checkpoint(run.id, frozen_policy_revision):
                return (await self._store.get_scan_run(run.id))[0]

            async def record_index_progress(increments: dict[str, int]) -> None:
                nonlocal run
                run = await self._store.add_scan_counters(
                    run.id, increments, updated_at=self._clock()
                )
                if self._events is not None:
                    await self._events.publish(run, event="scan.progress", counter=True)

            index_counts = await self._indexer.index(
                run,
                frozen_policy_revision,
                self.checkpoint,
                progress=record_index_progress,
            )
            if index_counts["identification_enqueued"]:
                run = await self._store.add_scan_counters(
                    run.id,
                    {
                        "identification_enqueued_count": index_counts[
                            "identification_enqueued"
                        ]
                    },
                    updated_at=self._clock(),
                )
                if self._events is not None:
                    await self._events.publish(run, event="scan.progress", counter=True)
            run, scopes, _ = await self._store.get_scan_run(run.id)
            if not await self.checkpoint(run.id, frozen_policy_revision):
                return (await self._store.get_scan_run(run.id))[0]
            run = await self._store.transition_scan_run(
                run.id,
                expected_state="indexing",
                expected_revision=run.row_revision,
                new_state="reconciling",
                now=self._clock(),
            )
            if self._events is not None:
                await self._events.publish(run, event="scan.transition")

        reconcile_counts = await self._reconciler.reconcile(
            run.id, scopes, self.checkpoint
        )
        run = await self._store.add_scan_counters(
            run.id,
            {
                "missing_count": reconcile_counts["missing"],
                "excluded_count": reconcile_counts["excluded"],
                "identification_enqueued_count": reconcile_counts[
                    "identification_enqueued"
                ],
            },
            updated_at=self._clock(),
        )
        run, _, _ = await self._store.get_scan_run(run.id)
        if not await self.checkpoint(run.id, frozen_policy_revision):
            return (await self._store.get_scan_run(run.id))[0]
        run = await self._store.transition_scan_run(
            run.id,
            expected_state="reconciling",
            expected_revision=run.row_revision,
            new_state="completed",
            now=self._clock(),
        )
        if self._events is not None:
            await self._events.publish(run, event="scan.transition")
        return run
