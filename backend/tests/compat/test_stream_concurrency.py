"""Fair and bounded media concurrency for both compatibility protocols."""

import asyncio

import pytest

from services.compat.stream_concurrency import (
    StreamCapacityError,
    StreamConcurrencyService,
    leased_chunks,
)

pytestmark = pytest.mark.asyncio


async def _wait_for_waiters(gate, count: int) -> None:
    for _ in range(50):
        if gate.waiter_count == count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} waiters, got {gate.waiter_count}")


async def test_waiting_principal_does_not_block_an_eligible_principal():
    service = StreamConcurrencyService(
        direct_global_limit=2,
        direct_principal_limit=1,
        wait_timeout_seconds=1,
    )
    first = await service.acquire_direct("alice")
    alice_waiter = asyncio.create_task(service.acquire_direct("alice"))
    await _wait_for_waiters(service.direct, 1)
    bob_waiter = asyncio.create_task(service.acquire_direct("bob"))

    bob = await asyncio.wait_for(bob_waiter, timeout=0.2)
    assert service.direct.active == 2
    assert alice_waiter.done() is False

    await first.release()
    second_alice = await asyncio.wait_for(alice_waiter, timeout=0.2)
    await bob.release()
    await second_alice.release()
    assert service.direct.active == 0
    assert service.direct.principal_count == 0


async def test_queue_is_bounded_and_timeout_removes_waiter_state():
    service = StreamConcurrencyService(
        direct_global_limit=1,
        direct_principal_limit=1,
        max_waiters=1,
        wait_timeout_seconds=0.01,
    )
    active = await service.acquire_direct("alice")
    waiter = asyncio.create_task(service.acquire_direct("bob"))
    await _wait_for_waiters(service.direct, 1)

    with pytest.raises(StreamCapacityError, match="queue is full"):
        await service.acquire_direct("carol")
    with pytest.raises(StreamCapacityError, match="wait expired"):
        await waiter
    assert service.direct.waiter_count == 0

    await active.release()
    assert service.direct.principal_count == 0


async def test_direct_and_transcode_pools_do_not_starve_each_other():
    service = StreamConcurrencyService(
        direct_global_limit=1,
        direct_principal_limit=1,
        transcode_global_limit=1,
        transcode_principal_limit=1,
    )
    direct = await service.acquire_direct("alice")
    transcode = await service.acquire_transcode("alice")
    assert service.direct.active == 1
    assert service.transcode.active == 1
    await direct.release()
    await transcode.release()


async def test_direct_lease_releases_when_source_raises():
    service = StreamConcurrencyService(direct_global_limit=1)
    lease = await service.acquire_direct("alice")

    async def broken_source():
        yield b"first"
        raise RuntimeError("read failed")

    iterator = leased_chunks(broken_source(), lease)
    assert await anext(iterator) == b"first"
    with pytest.raises(RuntimeError, match="read failed"):
        await anext(iterator)
    assert service.direct.active == 0


async def test_direct_lease_releases_when_consumer_cancels():
    service = StreamConcurrencyService(direct_global_limit=1)
    lease = await service.acquire_direct("alice")
    started = asyncio.Event()

    async def source():
        started.set()
        await asyncio.Event().wait()
        yield b"unreachable"

    async def consume():
        async for _ in leased_chunks(source(), lease):
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service.direct.active == 0
