"""Compat-scoped CORS for /subsonic + /jellyfin only (08-security.md s5).

Wildcard origin with credentials OFF is safe because compat auth is an explicit
token/secret, never an ambient cookie. OPTIONS preflight short-circuits before
auth (it carries no credentials and must not 401).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

_PREFIXES = ("/subsonic", "/jellyfin")
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": (
        "Authorization, X-Emby-Token, X-MediaBrowser-Token, "
        "X-Emby-Authorization, Content-Type, Range"
    ),
    "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
    "Access-Control-Max-Age": "600",
}


class CompatCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith(_PREFIXES):
            return await call_next(request)
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=_CORS_HEADERS)
        response = await call_next(request)
        for key, value in _CORS_HEADERS.items():
            response.headers[key] = value
        return response
