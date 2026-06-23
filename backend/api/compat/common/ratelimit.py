"""Compat-scoped rate limiting (08-security.md s3).

Global browse bucket + strict per-IP bucket on the auth-issuing endpoint
(brute-force target). Streaming is exempt: a seek-heavy player fires many Range
GETs and throttling would stutter playback. Rejections render the protocol shape
(Subsonic failed envelope / Jellyfin 429), never the native envelope.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from api.compat.subsonic.serialization import render_error
from infrastructure.resilience.rate_limiter import TokenBucketRateLimiter

_PREFIXES = ("/subsonic", "/jellyfin")
_STREAM_MARKERS = ("/stream", "/download", "/universal", "/audio/")
_MAX_IP_BUCKETS = 10_000


def _is_streaming(path: str) -> bool:
    low = path.lower()
    return any(marker in low for marker in _STREAM_MARKERS)


def _is_auth_issuing(request, path: str) -> bool:
    return request.method == "POST" and path == "/jellyfin/Users/AuthenticateByName"


def _client_ip(request) -> str:
    # rightmost X-Forwarded-For entry is the hop our own proxy appends; the leftmost
    # is attacker-set and could be spoofed to evade the per-IP brute-force bucket
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class CompatRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._browse = TokenBucketRateLimiter(30.0, 120)        # generous
        self._auth_by_ip: dict[str, TokenBucketRateLimiter] = {}  # strict, per-IP

    def _auth_limiter(self, ip: str) -> TokenBucketRateLimiter:
        limiter = self._auth_by_ip.get(ip)
        if limiter is None:
            if len(self._auth_by_ip) >= _MAX_IP_BUCKETS:
                self._auth_by_ip.clear()  # crude cap; resets the whole map
            limiter = TokenBucketRateLimiter(2.0, 5)
            self._auth_by_ip[ip] = limiter
        return limiter

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not path.startswith(_PREFIXES) or _is_streaming(path):
            return await call_next(request)
        if _is_auth_issuing(request, path):
            limiter = self._auth_limiter(_client_ip(request))
        else:
            limiter = self._browse
        if not await limiter.try_acquire():
            return self._reject(request, path)
        return await call_next(request)

    @staticmethod
    def _reject(request, path: str) -> Response:
        if path.startswith("/subsonic"):
            fmt = request.query_params.get("f", "xml")
            callback = request.query_params.get("callback")
            return render_error(0, "Rate limit exceeded", fmt=fmt, callback=callback)
        return Response(status_code=429)
