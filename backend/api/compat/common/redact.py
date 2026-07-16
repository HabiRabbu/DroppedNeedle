"""Log-safe request paths for the compat surface (08-security.md s2.1).

Subsonic puts credentials in the query string (p/t/s/apiKey) on every request;
never log request.url raw, use redacted_path() so secrets stay out of logs.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode

_SECRET_QS_KEYS = frozenset(
    {
        "p",
        "t",
        "s",
        "apikey",
        "api_key",
        "pw",
        "password",
        "token",
        "transcodeparams",
    }
)
_MASK = "***"


def redact_request_target(target: str) -> str:
    """Return an access-log-safe path/query request target.

    Uvicorn 0.37 supplies the raw path-with-query as argument index 2 on
    ``uvicorn.access`` records. Parsing also catches percent-encoded key names and
    preserves repeated parameters without depending on route code.
    """
    path, separator, query = target.partition("?")
    if not separator:
        return target
    safe = [
        (key, _MASK if key.casefold() in _SECRET_QS_KEYS else value)
        for key, value in parse_qsl(query, keep_blank_values=True)
    ]
    return f"{path}?{urlencode(safe)}"


class UvicornAccessCredentialFilter(logging.Filter):
    """Sanitize the installed Uvicorn access-record argument shape in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (
            record.name == "uvicorn.access"
            and isinstance(args, tuple)
            and len(args) == 5
            and isinstance(args[2], str)
        ):
            mutable = list(args)
            mutable[2] = redact_request_target(args[2])
            record.args = tuple(mutable)
        return True


_uvicorn_access_filter = UvicornAccessCredentialFilter()


def install_uvicorn_access_credential_filter() -> None:
    """Install the process-wide guarantee after Uvicorn configures its logger."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, UvicornAccessCredentialFilter) for item in logger.filters):
        logger.addFilter(_uvicorn_access_filter)


def redacted_path(request) -> str:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return redact_request_target(target)
