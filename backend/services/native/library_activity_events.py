"""Coalesced target activity revisions with bounded stream heartbeats."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import hashlib
from typing import Protocol

import msgspec

ACTIVITY_POLL_INTERVAL_SECONDS = 2.0
ACTIVITY_HEARTBEAT_POLLS = 15


class ActivityRevisionSource(Protocol):
    async def stream_revisions(self) -> dict[str, int]: ...


async def activity_events(
    source: ActivityRevisionSource,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    previous: dict[str, int] | None = None
    unchanged_polls = 0
    try:
        while True:
            revisions = await source.stream_revisions()
            if revisions != previous:
                revision_key = msgspec.json.encode(sorted(revisions.items()))
                event_id = f"activity:{hashlib.sha256(revision_key).hexdigest()[:16]}"
                payload = msgspec.json.encode(
                    {"id": event_id, "revisions": revisions}
                ).decode()
                yield f"id: {event_id}\nevent: activity.changed\ndata: {payload}\n\n"
                previous = revisions
                unchanged_polls = 0
            else:
                unchanged_polls += 1
                if unchanged_polls >= ACTIVITY_HEARTBEAT_POLLS:
                    yield ": keepalive\n\n"
                    unchanged_polls = 0
            await sleep(ACTIVITY_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:  # pragma: no cover - client disconnected
        return
