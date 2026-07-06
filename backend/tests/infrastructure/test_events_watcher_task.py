"""Events-watcher loop shape (scheduler-tick model): initial delay then a
catch-up sweep, exactly one sleep per iteration INCLUDING the error path,
cancellation breaks cleanly, the daily poll_time gates further sweeps and is
re-read every tick, plus the _next_daily_occurrence helper and the
kick-on-settings-save path."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from core import tasks


def _break_after(n: int):
    sleeps: list = []

    async def fake_sleep(secs):
        sleeps.append(secs)
        if len(sleeps) >= n:
            raise asyncio.CancelledError

    return sleeps, fake_sleep


def test_next_daily_occurrence():
    base = datetime(2026, 7, 6, 12, 0, 0)
    assert tasks._next_daily_occurrence("14:30", base) == datetime(2026, 7, 6, 14, 30)
    # wall time already passed today -> tomorrow
    assert tasks._next_daily_occurrence("06:00", base) == datetime(2026, 7, 7, 6, 0)
    # exactly-now counts as passed (strictly after)
    assert tasks._next_daily_occurrence("12:00", base) == datetime(2026, 7, 7, 12, 0)
    # garbage falls back to 06:00
    assert tasks._next_daily_occurrence("25:99", base) == datetime(2026, 7, 7, 6, 0)
    assert tasks._next_daily_occurrence("", base) == datetime(2026, 7, 7, 6, 0)


@pytest.mark.asyncio
async def test_catchup_sweep_then_waits_for_the_daily_slot(monkeypatch):
    # poll time = one minute ago, so the next occurrence is ~24h away:
    # exactly ONE catch-up sweep, then idle ticks
    sleeps, fake_sleep = _break_after(4)
    monkeypatch.setattr(tasks.asyncio, "sleep", fake_sleep)
    svc = AsyncMock()
    a_minute_ago = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")

    with pytest.raises(asyncio.CancelledError):
        await tasks.run_events_watcher_periodically(lambda: svc, lambda: a_minute_ago)

    assert svc.run_sweep.await_count == 1  # catch-up only; slot not reached again
    assert sleeps[0] == tasks._EVENTS_WATCHER_INITIAL_DELAY
    assert sleeps[1:] == [tasks._EVENTS_SCHEDULER_TICK] * 3  # one sleep per tick


@pytest.mark.asyncio
async def test_sweeps_every_time_the_slot_comes_due(monkeypatch):
    sleeps, fake_sleep = _break_after(4)
    monkeypatch.setattr(tasks.asyncio, "sleep", fake_sleep)
    # every tick is due: next occurrence is always in the past
    monkeypatch.setattr(
        tasks, "_next_daily_occurrence", lambda hhmm, after: after - timedelta(seconds=1)
    )
    svc = AsyncMock()
    poll_times: list[int] = []

    def get_poll_time() -> str:
        poll_times.append(1)
        return "06:00"

    with pytest.raises(asyncio.CancelledError):
        await tasks.run_events_watcher_periodically(lambda: svc, get_poll_time)

    assert svc.run_sweep.await_count == 3  # catch-up + one per due tick
    assert len(poll_times) == 2  # re-read on every non-catch-up tick


@pytest.mark.asyncio
async def test_loop_survives_a_failed_sweep_with_one_sleep_per_iteration(monkeypatch):
    sleeps, fake_sleep = _break_after(3)
    monkeypatch.setattr(tasks.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        tasks, "_next_daily_occurrence", lambda hhmm, after: after - timedelta(seconds=1)
    )
    svc = AsyncMock()
    svc.run_sweep.side_effect = [RuntimeError("boom"), None]

    with pytest.raises(asyncio.CancelledError):
        await tasks.run_events_watcher_periodically(lambda: svc, lambda: "06:00")

    assert svc.run_sweep.await_count == 2  # the error did not kill the loop
    assert sleeps[0] == tasks._EVENTS_WATCHER_INITIAL_DELAY
    # exactly one sleep per iteration, error path included
    assert sleeps[1:] == [tasks._EVENTS_SCHEDULER_TICK] * 2


@pytest.mark.asyncio
async def test_cancellation_during_sweep_breaks_cleanly(monkeypatch):
    sleeps, fake_sleep = _break_after(10)
    monkeypatch.setattr(tasks.asyncio, "sleep", fake_sleep)
    svc = AsyncMock()
    svc.run_sweep.side_effect = asyncio.CancelledError

    await tasks.run_events_watcher_periodically(lambda: svc, lambda: "06:00")

    assert svc.run_sweep.await_count == 1
    assert sleeps == [tasks._EVENTS_WATCHER_INITIAL_DELAY]  # no post-cancel sleep


@pytest.mark.asyncio
async def test_kick_runs_one_sweep_and_skips_while_in_flight(monkeypatch):
    monkeypatch.setattr(tasks, "_events_kick_task", None)
    started = asyncio.Event()
    release = asyncio.Event()
    sweeps = []

    class _Watcher:
        async def run_sweep(self):
            sweeps.append(1)
            started.set()
            await release.wait()

    task = tasks.kick_events_sweep(lambda: _Watcher())
    assert task is not None
    await started.wait()
    # a second save while the kicked sweep is still running is a no-op
    assert tasks.kick_events_sweep(lambda: _Watcher()) is None
    release.set()
    await task
    assert sweeps == [1]
    # once finished, the next save kicks again
    second = tasks.kick_events_sweep(lambda: _Watcher())
    assert second is not None
    await second


@pytest.mark.asyncio
async def test_kick_failure_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(tasks, "_events_kick_task", None)
    svc = AsyncMock()
    svc.run_sweep.side_effect = RuntimeError("boom")

    task = tasks.kick_events_sweep(lambda: svc)
    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError):
            await task  # awaiting surfaces it here, but production never awaits -
        await asyncio.sleep(0)  # let the done-callback run
    assert any("Kicked events sweep failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_watcher_resolved_fresh_for_every_due_sweep(monkeypatch):
    sleeps, fake_sleep = _break_after(4)  # initial delay + 3 ticks -> 3 sweeps
    monkeypatch.setattr(tasks.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        tasks, "_next_daily_occurrence", lambda hhmm, after: after - timedelta(seconds=1)
    )
    instances = [AsyncMock(), AsyncMock(), AsyncMock()]
    getter_calls: list[int] = []

    def getter():
        getter_calls.append(1)
        return instances[len(getter_calls) - 1]

    with pytest.raises(asyncio.CancelledError):
        await tasks.run_events_watcher_periodically(getter, lambda: "06:00")

    # a settings save rebuilds the watcher; each due sweep must use the current one
    assert len(getter_calls) == 3
    for instance in instances:
        assert instance.run_sweep.await_count == 1
