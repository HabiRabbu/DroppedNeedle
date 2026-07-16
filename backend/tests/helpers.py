"""Shared test helpers for observability / log field assertions."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.exception_handlers import (
    circuit_open_error_handler,
    client_disconnected_handler,
    configuration_error_handler,
    external_service_error_handler,
    general_exception_handler,
    http_exception_handler,
    request_validation_error_handler,
    resource_not_found_handler,
    source_resolution_error_handler,
    starlette_http_exception_handler,
    revision_overflow_error_handler,
    stale_revision_error_handler,
    validation_error_handler,
)
from core.exception_handlers import (
    conflict_error_handler,
    permission_denied_handler,
)
from core.exceptions import (
    ClientDisconnectedError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    PermissionDeniedError,
    ResourceNotFoundError,
    RevisionOverflowError,
    SourceResolutionError,
    StaleRevisionError,
    ValidationError,
)
from infrastructure.resilience.retry import CircuitOpenError
from infrastructure.persistence.auth_store import UserRecord
from middleware import _get_current_admin, _get_current_user


def mock_admin_user() -> UserRecord:
    """A fake authenticated admin user for overriding admin-gated routes in tests."""
    return UserRecord(
        id="test-admin-id",
        display_name="Test Admin",
        role="admin",
        created_at="2024-01-01T00:00:00Z",
    )


def mock_user(role: str = "user", user_id: str = "test-user-id") -> UserRecord:
    """A fake authenticated user (default non-admin) for ownership tests."""
    return UserRecord(
        id=user_id,
        display_name="Test User",
        role=role,
        created_at="2024-01-01T00:00:00Z",
    )


def override_admin_auth(app: FastAPI) -> None:
    """Bypass the admin-auth dependency for routers gated by `_get_current_admin`."""
    app.dependency_overrides[_get_current_admin] = mock_admin_user


def override_user_auth(
    app: FastAPI, role: str = "user", user_id: str = "test-user-id"
) -> None:
    """Bypass the user-auth dependency (`_get_current_user`) with a chosen role/id.

    Used by the request-ownership tests (403 vs 200) - the route resolves
    ``CurrentUserDep`` via ``_get_current_user``.
    """
    app.dependency_overrides[_get_current_user] = lambda: mock_user(
        role=role, user_id=user_id
    )


def add_production_exception_handlers(app: FastAPI) -> FastAPI:
    app.add_exception_handler(ClientDisconnectedError, client_disconnected_handler)
    app.add_exception_handler(ResourceNotFoundError, resource_not_found_handler)
    app.add_exception_handler(ExternalServiceError, external_service_error_handler)
    app.add_exception_handler(CircuitOpenError, circuit_open_error_handler)
    app.add_exception_handler(ValidationError, validation_error_handler)
    app.add_exception_handler(ConfigurationError, configuration_error_handler)
    app.add_exception_handler(PermissionDeniedError, permission_denied_handler)
    app.add_exception_handler(ConflictError, conflict_error_handler)
    app.add_exception_handler(StaleRevisionError, stale_revision_error_handler)
    app.add_exception_handler(RevisionOverflowError, revision_overflow_error_handler)
    app.add_exception_handler(SourceResolutionError, source_resolution_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, starlette_http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    return app


def build_test_client(app: FastAPI) -> TestClient:
    add_production_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def make_builtin_dispatcher(get_download_service):
    """An AcquisitionDispatcher wired so a configured download client always wins:
    it forwards request_album/request_track straight to get_download_service. Lets
    tests that predate Free Music assert download dispatch unchanged."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from services.acquisition_dispatcher import AcquisitionDispatcher

    free_music = MagicMock()
    free_music.is_ready = MagicMock(return_value=False)
    return AcquisitionDispatcher(
        get_download_service=get_download_service,
        get_free_music_service=lambda: free_music,
        preferences_service=SimpleNamespace(is_builtin_download_ready=lambda: True),
    )


def assert_log_fields(
    records: list[logging.LogRecord],
    prefix: str,
    required_fields: list[str],
    *,
    min_count: int = 1,
) -> list[str]:
    """Assert that log records matching *prefix* contain all *required_fields*.

    Returns the matching messages for further inspection.

    Parameters
    ----------
    records:
        ``caplog.records`` or equivalent list of ``LogRecord``.
    prefix:
        The log message prefix to filter on (e.g. ``"audiodb.cache"``).
    required_fields:
        Key names that must appear as ``key=`` in every matching message.
    min_count:
        Minimum number of matching records expected (default 1).
    """
    matching = [r.message for r in records if r.message.startswith(prefix)]
    assert (
        len(matching) >= min_count
    ), f"Expected >= {min_count} log(s) starting with '{prefix}', found {len(matching)}"
    for msg in matching:
        for field in required_fields:
            assert f"{field}=" in msg, f"Field '{field}=' missing in log: {msg}"
    return matching
