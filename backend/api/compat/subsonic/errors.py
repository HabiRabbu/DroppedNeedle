"""Python exception -> Subsonic error-code mapping for the inbound compat shim.

Standard Subsonic error codes (reference/subsonic-opensubsonic-api.md s1):
    0  generic error
    10 required parameter missing
    40 wrong username or password
    43 multiple conflicting authentication mechanisms (OS apiKey extension)
    44 invalid apiKey (OS apiKey extension)
    50 user not authorized for the operation
    70 requested data not found
"""

from __future__ import annotations

from core.exceptions import (
    ConflictError,
    DroppedNeedleException,
    PermissionDeniedError,
    ResourceNotFoundError,
    SubsonicError,
    ValidationError,
)

GENERIC = 0
PARAM_MISSING = 10
WRONG_CREDENTIALS = 40
CONFLICTING_AUTH = 43
INVALID_APIKEY = 44
NOT_AUTHORIZED = 50
NOT_FOUND = 70

_DEFAULT_MESSAGES: dict[int, str] = {
    0: "An error occurred.",
    10: "Required parameter is missing.",
    40: "Wrong username or password.",
    43: "Multiple conflicting authentication mechanisms provided.",
    44: "Invalid API key.",
    50: "User is not authorized for the given operation.",
    70: "The requested data was not found.",
}


def to_subsonic_code(exc: Exception) -> int:
    """Map an exception to a Subsonic error code.

    SubsonicError carries its own code; mapping the base hierarchy covers subclasses
    (NotFound -> 70, Validation -> 10) so service failures never hit the global handlers.
    """
    if isinstance(exc, SubsonicError):
        return exc.code
    if isinstance(exc, ResourceNotFoundError):
        return NOT_FOUND
    if isinstance(exc, PermissionDeniedError):
        return NOT_AUTHORIZED
    if isinstance(exc, ConflictError):
        return GENERIC
    if isinstance(exc, ValidationError):
        return PARAM_MISSING
    return GENERIC


def to_subsonic_message(exc: Exception, code: int) -> str:
    """Message for the failed envelope. Only our own exceptions surface their text;
    an unexpected str() can leak paths/ids, so fall back to the static code default."""
    if isinstance(exc, DroppedNeedleException):
        message = str(getattr(exc, "message", "") or exc).strip()
        if message:
            return message
    return _DEFAULT_MESSAGES.get(code, _DEFAULT_MESSAGES[GENERIC])
