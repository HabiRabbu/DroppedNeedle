"""Durable-revision scan invalidations with counter-rate throttling."""

from __future__ import annotations

import time
from collections.abc import Callable

from infrastructure.persistence.native_library_store import NativeLibraryStore
from infrastructure.sse_publisher import SSEPublisher
from models.library_work import ScanRun

SCAN_EVENT_CHANNEL = "target-library-scan"
COUNTER_EVENT_INTERVAL_SECONDS = 2.0


class LibraryScanEventPublisher:
    def __init__(
        self,
        store: NativeLibraryStore,
        publisher: SSEPublisher,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._clock = clock
        self._last_counter_event: dict[str, float] = {}

    async def publish(self, run: ScanRun, *, event: str, counter: bool = False) -> bool:
        now = self._clock()
        last = self._last_counter_event.get(run.id)
        if counter and last is not None and now - last < COUNTER_EVENT_INTERVAL_SECONDS:
            return False
        if counter:
            self._last_counter_event[run.id] = now
        stream_revision = await self._store.get_stream_revision("scan")
        await self._publisher.publish(
            SCAN_EVENT_CHANNEL,
            event,
            {
                "id": f"scan:{stream_revision}",
                "stream_kind": "scan",
                "stream_revision": stream_revision,
                "run_id": run.id,
                "row_revision": run.row_revision,
                "event_revision": run.event_revision,
                "state": run.state,
            },
        )
        return True
