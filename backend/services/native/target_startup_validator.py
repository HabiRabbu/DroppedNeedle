"""Fail-closed validation for the separately started target-only application."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Literal

from core.exceptions import TargetStartupInvariantError
from infrastructure.persistence.native_library_store import NativeLibraryStore

logger = logging.getLogger(__name__)

TargetStartupValidationPhase = Literal["cutover", "admission", "steady_state"]


class TargetStartupValidator:
    def __init__(
        self,
        store: NativeLibraryStore,
        configured_root_ids: Callable[[], set[str]] | None = None,
        emit_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._store = store
        self._configured_root_ids = configured_root_ids
        self._emit_progress = emit_progress or (lambda _message: None)

    async def validate(self, phase: TargetStartupValidationPhase) -> dict[str, Any]:
        started = time.perf_counter()
        self._emit_progress("Validating the migration marker and catalog revision.")
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
        self._emit_progress("Checking catalog integrity.")
        invariants = await self._store.validate_catalog_integrity()
        if phase in {"cutover", "admission"}:
            self._emit_progress("Checking all migrated saved references.")
            invariants = {
                **invariants,
                "unresolved_references": (
                    await self._store.validate_migration_references()
                ),
            }
        elif phase != "steady_state":
            raise ValueError(f"Unsupported target startup validation phase: {phase}")
        failures = {name: count for name, count in invariants.items() if count != 0}
        if failures:
            logger.error(
                "target_startup.catalog_integrity_failed phase=%s counters=%s",
                phase,
                ",".join(f"{name}={count}" for name, count in sorted(failures.items())),
            )
            raise TargetStartupInvariantError(
                "The target catalog failed startup integrity validation."
            )
        if phase in {"cutover", "admission"} and self._configured_root_ids is not None:
            self._emit_progress("Checking configured library roots.")
            configured = self._configured_root_ids()
            migrated = await self._store.get_migrated_root_ids()
            if configured != migrated:
                raise TargetStartupInvariantError(
                    "The configured library roots do not match the migrated catalog."
                )
        elapsed_seconds = time.perf_counter() - started
        logger.info(
            "target_startup.catalog_integrity_completed phase=%s elapsed_seconds=%.3f",
            phase,
            elapsed_seconds,
        )
        return {**state, "invariants": invariants}
