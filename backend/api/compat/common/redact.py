"""Log-safe request paths for the compat surface (08-security.md s2.1).

Subsonic puts credentials in the query string (p/t/s/apiKey) on every request;
never log request.url raw, use redacted_path() so secrets stay out of logs.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

_SECRET_QS_KEYS = frozenset(
    {"p", "t", "s", "apikey", "api_key", "pw", "password", "token"}
)


def redacted_path(request) -> str:
    q = request.url.query
    if not q:
        return request.url.path
    safe = [
        (k, "***" if k.lower() in _SECRET_QS_KEYS else v)
        for k, v in parse_qsl(q, keep_blank_values=True)
    ]
    return f"{request.url.path}?{urlencode(safe)}"
