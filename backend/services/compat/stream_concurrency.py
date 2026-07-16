"""Fair, bounded concurrency leases for compatibility media responses."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import AsyncGenerator, AsyncIterable


class StreamCapacityError(Exception):
    """The bounded stream queue is full or its wait deadline expired."""


@dataclass(eq=False)
class _Waiter:
    principal: str


class StreamLease:
    def __init__(self, gate: "_FairGate", principal: str) -> None:
        self._gate = gate
        self._principal = principal
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._gate.release(self._principal)

    async def __aenter__(self) -> "StreamLease":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.release()


class _FairGate:
    def __init__(
        self,
        *,
        global_limit: int,
        principal_limit: int,
        max_waiters: int,
        wait_timeout_seconds: float,
    ) -> None:
        self._global_limit = global_limit
        self._principal_limit = principal_limit
        self._max_waiters = max_waiters
        self._wait_timeout_seconds = wait_timeout_seconds
        self._active = 0
        self._active_by_principal: dict[str, int] = {}
        self._waiters: deque[_Waiter] = deque()
        self._condition = asyncio.Condition()

    def _first_eligible(self) -> _Waiter | None:
        if self._active >= self._global_limit:
            return None
        for waiter in self._waiters:
            if self._active_by_principal.get(waiter.principal, 0) < self._principal_limit:
                return waiter
        return None

    async def acquire(self, principal: str) -> StreamLease:
        waiter = _Waiter(principal)
        async with self._condition:
            if len(self._waiters) >= self._max_waiters:
                raise StreamCapacityError("stream queue is full")
            self._waiters.append(waiter)
            try:
                async with asyncio.timeout(self._wait_timeout_seconds):
                    while self._first_eligible() is not waiter:
                        await self._condition.wait()
                self._waiters.remove(waiter)
                self._active += 1
                self._active_by_principal[principal] = (
                    self._active_by_principal.get(principal, 0) + 1
                )
                self._condition.notify_all()
                return StreamLease(self, principal)
            except TimeoutError as exc:
                self._waiters.remove(waiter)
                self._condition.notify_all()
                raise StreamCapacityError("stream queue wait expired") from exc
            except BaseException:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                    self._condition.notify_all()
                raise

    async def release(self, principal: str) -> None:
        async with self._condition:
            current = self._active_by_principal.get(principal, 0)
            if current <= 1:
                self._active_by_principal.pop(principal, None)
            else:
                self._active_by_principal[principal] = current - 1
            self._active -= 1
            self._condition.notify_all()

    @property
    def active(self) -> int:
        return self._active

    @property
    def principal_count(self) -> int:
        return len(self._active_by_principal)

    @property
    def waiter_count(self) -> int:
        return len(self._waiters)


class StreamConcurrencyService:
    """Separate fair pools prevent direct reads and ffmpeg work starving each other."""

    def __init__(
        self,
        *,
        direct_global_limit: int = 32,
        direct_principal_limit: int = 8,
        transcode_global_limit: int = 2,
        transcode_principal_limit: int = 1,
        max_waiters: int = 128,
        wait_timeout_seconds: float = 5.0,
    ) -> None:
        self.direct = _FairGate(
            global_limit=direct_global_limit,
            principal_limit=direct_principal_limit,
            max_waiters=max_waiters,
            wait_timeout_seconds=wait_timeout_seconds,
        )
        self.transcode = _FairGate(
            global_limit=transcode_global_limit,
            principal_limit=transcode_principal_limit,
            max_waiters=max_waiters,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    async def acquire_direct(self, principal: str) -> StreamLease:
        return await self.direct.acquire(principal)

    async def acquire_transcode(self, principal: str) -> StreamLease:
        return await self.transcode.acquire(principal)


async def leased_chunks(
    chunks: AsyncIterable[bytes], lease: StreamLease
) -> AsyncGenerator[bytes, None]:
    """Release a direct-stream lease on exhaustion, error, or cancellation."""
    try:
        async for chunk in chunks:
            yield chunk
    finally:
        await lease.release()
