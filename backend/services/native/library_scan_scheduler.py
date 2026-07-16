"""Automatic target scan requests derived only from durable terminal runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from models.library_work import ScanRequest, ScanScope
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_scan_coordinator import LibraryScanCoordinator
from services.native.library_schedule_service import LibraryScheduleService


class LibraryAutomaticScanScheduler:
    def __init__(self, schedule: LibraryScheduleService | None = None) -> None:
        self._schedule = schedule or LibraryScheduleService()

    async def tick(
        self,
        coordinator: LibraryScanCoordinator,
        resolver: LibraryPolicyResolver,
        *,
        frequency: str,
        daily_time: str,
        timezone_name: str,
        now: datetime,
    ) -> bool:
        if frequency == "manual":
            return False
        anchor = await coordinator.latest_filesystem_terminal()
        terminal_at = anchor.terminal_at if anchor is not None else None
        remaining = self._schedule.seconds_until_due(
            frequency,
            daily_time,
            terminal_at,
            now=now,
            timezone_name=timezone_name,
        )
        if remaining is None or remaining > 0:
            return False
        scopes = self._scheduled_scopes(resolver)
        if not scopes:
            return False
        await coordinator.request_run(
            ScanRequest(
                kind="incremental",
                trigger="automatic",
                policy_revision=resolver.policy_revision,
                scopes=scopes,
            )
        )
        return True

    @staticmethod
    def _scheduled_scopes(resolver: LibraryPolicyResolver) -> list[ScanScope]:
        scopes: list[ScanScope] = []
        for root in resolver.settings.library_roots:
            if root.policy != "excluded":
                scopes.append(
                    ScanScope(
                        root_id=root.id,
                        scope_id=root.id,
                        relative_path=".",
                        root_path=root.path,
                        effective_policy=root.policy,
                        policy_revision=resolver.policy_revision,
                    )
                )
                continue
            selected_paths: list[PurePosixPath] = []
            for rule in getattr(root, "rules", []):
                if rule.policy == "excluded":
                    continue
                rule_path = PurePosixPath(rule.relative_path)
                if any(rule_path.is_relative_to(parent) for parent in selected_paths):
                    continue
                selected_paths.append(rule_path)
                scopes.append(
                    ScanScope(
                        root_id=root.id,
                        scope_id=rule.id,
                        relative_path=rule.relative_path,
                        root_path=root.path,
                        effective_policy=rule.policy,
                        policy_revision=resolver.policy_revision,
                    )
                )
        return scopes
