"""In-process registry of degraded external-service capabilities.

Single source of truth for "is <service> currently degraded?", read by both the
fallback logic (skip the dead source, use the fallback) and the UI status indicator.
Entries auto-expire after a TTL that is refreshed on every fresh degraded signal, so
a capability heals on its own once the upstream stops reporting itself down - no
manual reset, no background sweeper.

Single-process invariant: like the app's other singletons/limiters, this lives in one
uvicorn worker. It is deliberately signal-driven - we only mark a capability degraded
on an UNAMBIGUOUS upstream signal (e.g. ListenBrainz literally replying "currently
disabled" / "provide an Auth token"), never on a transient timeout, so it reflects a
genuine outage rather than a blip.
"""

import time
from typing import Callable

import msgspec


class ServiceHealthEntry(msgspec.Struct, frozen=True):
    service: str  # "listenbrainz"
    capability: str  # "popularity"
    severity: str  # "degraded" | "down"
    message: str  # user-facing, one line
    fallback: str | None  # what we're using instead, e.g. "lastfm"
    degraded_seconds: int  # how long it's been degraded (for the UI)


class ServiceHealthRegistry:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # (service, capability) -> (severity, message, fallback, since, until)
        self._entries: dict[tuple[str, str], tuple[str, str, str | None, float, float]] = {}

    def mark_degraded(
        self,
        service: str,
        capability: str,
        *,
        message: str,
        fallback: str | None = None,
        severity: str = "degraded",
        ttl_seconds: float = 300.0,
    ) -> None:
        """Record (or refresh) a degraded capability. The TTL slides forward on every
        call, so as long as the upstream keeps reporting itself down the entry stays
        live; once the signals stop, it expires and the capability is considered healthy
        again on the next check."""
        now = self._clock()
        key = (service, capability)
        existing = self._entries.get(key)
        since = existing[3] if existing else now
        self._entries[key] = (severity, message, fallback, since, now + ttl_seconds)

    def is_degraded(self, service: str, capability: str | None = None) -> bool:
        now = self._clock()
        for (svc, cap), (_sev, _msg, _fb, _since, until) in self._entries.items():
            if until >= now and svc == service and (capability is None or cap == capability):
                return True
        return False

    def current(self) -> list[ServiceHealthEntry]:
        """Live degraded entries; prunes expired ones as a side effect."""
        now = self._clock()
        expired = [k for k, v in self._entries.items() if v[4] < now]
        for k in expired:
            self._entries.pop(k, None)
        out: list[ServiceHealthEntry] = []
        for (svc, cap), (sev, msg, fb, since, _until) in self._entries.items():
            out.append(
                ServiceHealthEntry(
                    service=svc,
                    capability=cap,
                    severity=sev,
                    message=msg,
                    fallback=fb,
                    degraded_seconds=int(now - since),
                )
            )
        out.sort(key=lambda e: (e.service, e.capability))
        return out

    def clear(self) -> None:
        self._entries.clear()


service_health = ServiceHealthRegistry()
