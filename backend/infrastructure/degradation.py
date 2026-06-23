"""Request-scoped degradation context via ``contextvars``.

A :class:`DegradationContext` is created per HTTP request by the
:class:`DegradationMiddleware` and can be accessed from *any* layer
(repository, service, route) without threading extra arguments through
call signatures.
"""

from __future__ import annotations

import contextvars

from infrastructure.integration_result import IntegrationResult, IntegrationStatus

_degradation_ctx_var: contextvars.ContextVar[DegradationContext | None] = (
    contextvars.ContextVar("degradation_ctx", default=None)
)


class DegradationContext:
    """Accumulates per-source integration status within a single request."""

    __slots__ = ("_services",)

    def __init__(self) -> None:
        self._services: dict[str, IntegrationStatus] = {}

    def record(self, result: IntegrationResult) -> None:  # type: ignore[type-arg]
        """Record an integration result, keeping the worst status per source."""
        prev = self._services.get(result.source)
        if prev is None or _severity(result.status) > _severity(prev):
            self._services[result.source] = result.status

    def summary(self) -> dict[str, str]:
        """Return ``{source: status}`` for all recorded integrations."""
        return dict(self._services)

    def degraded_summary(self) -> dict[str, str]:
        """Return only sources that are *not* ``ok``."""
        return {k: v for k, v in self._services.items() if v != "ok"}

    def has_degradation(self) -> bool:
        return any(v != "ok" for v in self._services.values())




def init_degradation_context() -> DegradationContext:
    """Create a fresh context and install it in the current ``ContextVar``."""
    ctx = DegradationContext()
    _degradation_ctx_var.set(ctx)
    return ctx


def get_degradation_context() -> DegradationContext:
    """Return the current request's context.

    Raises :class:`RuntimeError` when called outside a request scope.
    """
    ctx = _degradation_ctx_var.get()
    if ctx is None:
        raise RuntimeError(
            "get_degradation_context() called outside a request scope"
        )
    return ctx


def try_get_degradation_context() -> DegradationContext | None:
    """Return the current context, or ``None`` if none is active.

    Safe for background tasks / startup code where no request is in
    flight.
    """
    return _degradation_ctx_var.get()


def clear_degradation_context() -> None:
    """Remove the current context (end-of-request cleanup)."""
    _degradation_ctx_var.set(None)



_SEVERITY: dict[IntegrationStatus, int] = {"ok": 0, "degraded": 1, "error": 2}


def _severity(status: IntegrationStatus) -> int:
    return _SEVERITY[status]
