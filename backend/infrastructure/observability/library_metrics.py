"""Thread-safe aggregate measurements for native-library workloads.

The collector is intentionally transport-neutral. Scan, identification, benchmark, and
operation services own when a measurement begins; this module only aggregates counters,
timings, distributions, and high-water marks into a serializable snapshot.
"""

from __future__ import annotations

import asyncio
import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator

from infrastructure.memory import get_rss_bytes

LIBRARY_COUNTERS = (
    "walks",
    "stats",
    "tag_reads",
    "fingerprints",
    "external_calls",
    "sql_statements",
    "sql_transactions",
    "sse_events",
    "sse_counter_events",
    "playback_starts",
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[rank]


@dataclass(frozen=True)
class DistributionSnapshot:
    count: int
    total: float
    minimum: float | None
    maximum: float | None
    p50: float | None
    p95: float | None
    p99: float | None


@dataclass(frozen=True)
class LibraryMetricsSnapshot:
    counters: dict[str, int]
    gauges: dict[str, float]
    peaks: dict[str, float]
    distributions: dict[str, DistributionSnapshot]


@dataclass
class LibraryMetrics:
    """Aggregate one workload without retaining per-file paths or payloads."""

    _counters: dict[str, int] = field(default_factory=dict)
    _gauges: dict[str, float] = field(default_factory=dict)
    _peaks: dict[str, float] = field(default_factory=dict)
    _observations: dict[str, list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def for_library_workload(cls) -> "LibraryMetrics":
        metrics = cls()
        for name in LIBRARY_COUNTERS:
            metrics.increment(name, 0)
        return metrics

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def set_peak(self, name: str, value: float) -> None:
        with self._lock:
            self._peaks[name] = max(value, self._peaks.get(name, value))

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._observations.setdefault(name, []).append(value)

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.observe(name, perf_counter() - started)

    def sample_rss(self) -> int | None:
        rss = get_rss_bytes()
        if rss is not None:
            self.set_peak("rss_bytes", float(rss))
        return rss

    def snapshot(self) -> LibraryMetricsSnapshot:
        with self._lock:
            distributions = {
                name: DistributionSnapshot(
                    count=len(values),
                    total=sum(values),
                    minimum=min(values) if values else None,
                    maximum=max(values) if values else None,
                    p50=_percentile(values, 0.50),
                    p95=_percentile(values, 0.95),
                    p99=_percentile(values, 0.99),
                )
                for name, values in self._observations.items()
            }
            return LibraryMetricsSnapshot(
                counters=dict(self._counters),
                gauges=dict(self._gauges),
                peaks=dict(self._peaks),
                distributions=distributions,
            )


async def sample_event_loop_delay(
    metrics: LibraryMetrics,
    *,
    duration_seconds: float,
    interval_seconds: float = 0.01,
) -> None:
    """Record scheduler delay without retaining task or file details."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration_seconds
    expected = loop.time() + interval_seconds
    while expected <= deadline:
        await asyncio.sleep(max(0.0, expected - loop.time()))
        metrics.observe("event_loop_delay_seconds", max(0.0, loop.time() - expected))
        expected += interval_seconds
