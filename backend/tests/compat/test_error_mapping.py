"""T0.11 - compat exception classes + per-shim error-code mapping."""

from api.compat.jellyfin.errors import to_jellyfin_status
from api.compat.subsonic.errors import to_subsonic_code, to_subsonic_message
from core.exceptions import (
    ConflictError,
    DroppedNeedleException,
    ExternalServiceError,
    JellyfinError,
    PermissionDeniedError,
    PlaylistNotFoundError,
    ResourceNotFoundError,
    SourceResolutionError,
    SubsonicError,
    ValidationError,
)


def test_subsonic_error_constructs_with_code_first_positional():
    err = SubsonicError(43)
    assert err.code == 43
    assert isinstance(err, DroppedNeedleException)
    assert err.message == ""
    err2 = SubsonicError(44, "bad key")
    assert err2.code == 44 and err2.message == "bad key"


def test_jellyfin_error_constructs_with_status_first_positional():
    err = JellyfinError(401)
    assert err.status == 401
    assert err.body is None
    assert isinstance(err, DroppedNeedleException)
    err2 = JellyfinError(404, "missing", {"detail": "x"})
    assert err2.status == 404 and err2.body == {"detail": "x"}


def test_subsonic_code_mapping():
    assert to_subsonic_code(SubsonicError(44)) == 44
    assert to_subsonic_code(ResourceNotFoundError("nope")) == 70
    assert to_subsonic_code(PermissionDeniedError("nope")) == 50
    assert to_subsonic_code(ConflictError("dupe")) == 0
    assert to_subsonic_code(ValidationError("bad")) == 10
    assert to_subsonic_code(RuntimeError("boom")) == 0


def test_subsonic_code_mapping_covers_subclasses():
    # PlaylistNotFoundError -> ResourceNotFoundError -> 70
    assert to_subsonic_code(PlaylistNotFoundError("x")) == 70
    # SourceResolutionError -> ValidationError -> 10
    assert to_subsonic_code(SourceResolutionError("x")) == 10


def test_subsonic_message_prefers_exception_text_then_default():
    assert to_subsonic_message(ResourceNotFoundError("track gone"), 70) == "track gone"
    assert to_subsonic_message(SubsonicError(70), 70) == "The requested data was not found."


def test_subsonic_message_does_not_leak_unexpected_exception_text():
    # An unexpected (non-DroppedNeedle) exception must NOT surface its str() to the client
    # - it can carry internal paths/ids - so it falls back to the static code default.
    leaky = RuntimeError("/srv/secret/path token=abc123")
    msg = to_subsonic_message(leaky, 0)
    assert "secret" not in msg and "abc123" not in msg
    assert msg == "An error occurred."


def test_jellyfin_status_mapping():
    assert to_jellyfin_status(JellyfinError(401)) == (401, None)
    assert to_jellyfin_status(JellyfinError(404, body={"a": 1})) == (404, {"a": 1})
    assert to_jellyfin_status(ResourceNotFoundError("nope")) == (404, None)
    assert to_jellyfin_status(PermissionDeniedError("nope")) == (403, None)
    assert to_jellyfin_status(ConflictError("dupe")) == (409, None)
    assert to_jellyfin_status(ValidationError("bad")) == (400, None)
    assert to_jellyfin_status(ExternalServiceError("upstream")) == (500, None)
    assert to_jellyfin_status(RuntimeError("boom")) == (500, None)


def test_jellyfin_status_mapping_covers_subclasses():
    assert to_jellyfin_status(PlaylistNotFoundError("x")) == (404, None)
    assert to_jellyfin_status(SourceResolutionError("x")) == (400, None)
