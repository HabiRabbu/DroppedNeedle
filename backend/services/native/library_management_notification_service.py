"""Deliver durable post-commit Library Management media-server refreshes."""

from __future__ import annotations

import time
from collections.abc import Callable

from core.exceptions import ExternalServiceError, JellyfinAuthError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_management import (
    EXTERNAL_REFRESH_AUTH_FAILED,
    EXTERNAL_REFRESH_FAILED,
)
from repositories.protocols import JellyfinRepositoryProtocol

NOTIFICATION_LEASE_SECONDS = 60.0


class LibraryManagementNotificationService:
    def __init__(
        self,
        store: NativeLibraryStore,
        jellyfin_getter: Callable[[], JellyfinRepositoryProtocol],
    ) -> None:
        self._store = store
        self._jellyfin_getter = jellyfin_getter

    async def recover(self, *, now: float | None = None) -> int:
        return await self._store.recover_expired_library_management_external_refreshes(
            now=time.time() if now is None else now
        )

    async def run_once(self, worker_id: str, *, now: float | None = None) -> str | None:
        timestamp = time.time() if now is None else now
        delivery = await self._store.claim_library_management_external_refresh(
            worker_id,
            now=timestamp,
            lease_seconds=NOTIFICATION_LEASE_SECONDS,
        )
        if delivery is None:
            return None
        try:
            if delivery.target != "jellyfin":
                raise ExternalServiceError("External refresh protocol unavailable")
            await self._jellyfin_getter().refresh_library()
        except JellyfinAuthError:
            await self._store.finish_library_management_external_refresh(
                delivery.id,
                worker_id,
                succeeded=False,
                retryable=False,
                failure_code=EXTERNAL_REFRESH_AUTH_FAILED,
                now=timestamp,
            )
        except ExternalServiceError:
            await self._store.finish_library_management_external_refresh(
                delivery.id,
                worker_id,
                succeeded=False,
                retryable=True,
                failure_code=EXTERNAL_REFRESH_FAILED,
                now=timestamp,
            )
        else:
            await self._store.finish_library_management_external_refresh(
                delivery.id,
                worker_id,
                succeeded=True,
                retryable=False,
                failure_code=None,
                now=timestamp,
            )
        return delivery.operation_job_id
