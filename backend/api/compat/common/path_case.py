"""Case-insensitive path routing for the compat shims.

Real Jellyfin (ASP.NET Core) and many Subsonic servers route paths
case-insensitively and some clients rely on it (Feishin POSTs
``/jellyfin/users/authenticatebyname``), but FastAPI matches case-sensitively, so
this canonicalises ``/subsonic`` / ``/jellyfin`` paths to the route's registered
casing before routing. Reconstruction from ``path_format`` is lossless because
every compat path param is a hex/uuid id, an int, or an already-lowercased value.

Must sit OUTSIDE the rate-limit middleware so its exact-path check sees the
canonical form.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

_PREFIXES = ("/subsonic", "/jellyfin")


class _Keep(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        return "{" + key + "}"


class CompatPathCaseMiddleware:
    def __init__(self, app: ASGIApp, routes: Iterable) -> None:
        self.app = app
        # (case-insensitive matcher, canonical path_format) for every compat route
        self._matchers: list[tuple[re.Pattern[str], str]] = []
        for route in routes:
            fmt = getattr(route, "path_format", None)
            rx = getattr(route, "path_regex", None)
            if fmt and rx is not None and fmt.startswith(_PREFIXES):
                self._matchers.append((re.compile(rx.pattern, re.IGNORECASE), fmt))

    def _canonical(self, path: str) -> str | None:
        for matcher, fmt in self._matchers:
            m = matcher.match(path)
            if not m:
                continue
            try:
                canon = fmt.format_map(_Keep(m.groupdict()))
            except (KeyError, IndexError, ValueError):  # pragma: no cover - defensive
                return None
            return canon if canon != path else None
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path.lower().startswith(_PREFIXES):
                canon = self._canonical(path)
                if canon is not None:
                    scope = dict(scope)
                    scope["path"] = canon
                    scope["raw_path"] = canon.encode("ascii", "ignore")
        await self.app(scope, receive, send)
