"""Fail-closed validation for the separately started target-only application."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.exceptions import TargetStartupInvariantError
from infrastructure.persistence.native_library_store import NativeLibraryStore


class TargetStartupValidator:
    def __init__(
        self,
        store: NativeLibraryStore,
        configured_root_ids: Callable[[], set[str]] | None = None,
    ) -> None:
        self._store = store
        self._configured_root_ids = configured_root_ids

    async def validate(self) -> dict[str, Any]:
        state = await self._store.get_target_startup_state()
        marker = state["marker"]
        migration = state["migration"]
        if marker is None or migration is None:
            raise TargetStartupInvariantError(
                "The completed legacy-catalog migration marker is missing."
            )
        if (
            migration["state"] != "completed"
            or migration["source_revision"] != marker["source_revision"]
            or migration["completed_at"] is None
        ):
            raise TargetStartupInvariantError(
                "The migration run does not match the completed target marker."
            )
        if int(marker["target_catalog_revision"]) > int(state["catalog_revision"]):
            raise TargetStartupInvariantError(
                "The target catalog revision predates its migration marker."
            )
        invariants = await self._store.validate_migrated_catalog()
        if any(value != 0 for value in invariants.values()):
            raise TargetStartupInvariantError(
                "The target catalog failed startup integrity validation."
            )
        if self._configured_root_ids is not None:
            configured = self._configured_root_ids()
            migrated = await self._store.get_migrated_root_ids()
            if configured != migrated:
                raise TargetStartupInvariantError(
                    "The configured library roots do not match the migrated catalog."
                )
        return {**state, "invariants": invariants}
