"""Post-cutover Subsonic scan projection staged without runtime registration."""

from __future__ import annotations

from models.library_work import ScanRequest, ScanScope
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_scan_coordinator import LibraryScanCoordinator


class TargetCompatScanService:
    def __init__(
        self,
        coordinator: LibraryScanCoordinator,
        resolver_getter,
    ) -> None:
        self._coordinator = coordinator
        self._resolver_getter = resolver_getter

    async def start_scan(self) -> None:
        resolver: LibraryPolicyResolver = self._resolver_getter()
        await self._coordinator.request_run(
            ScanRequest(
                kind="incremental",
                trigger="subsonic",
                policy_revision=resolver.policy_revision,
                scopes=[
                    ScanScope(
                        root_id=root.id,
                        relative_path=".",
                        effective_policy=root.policy,
                        policy_revision=resolver.policy_revision,
                    )
                    for root in resolver.settings.library_roots
                ],
            )
        )

    async def start(self) -> None:
        await self.start_scan()

    async def get_status(self) -> tuple[bool, int]:
        runs = await self._coordinator.current()
        active = next((run for run in runs if run.state != "queued"), None)
        if active is None:
            return False, 0
        snapshot = await self._coordinator.snapshot(active.id)
        return True, snapshot.counters.get("inspected_count", 0)

    async def status(self) -> tuple[bool, int]:
        return await self.get_status()
