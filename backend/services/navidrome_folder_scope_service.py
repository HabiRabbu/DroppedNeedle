"""Resolve per-user outbound Navidrome catalog scopes."""

from __future__ import annotations

import hashlib

import msgspec

from core.exceptions import ExternalServiceError
from infrastructure.resilience.retry import CircuitOpenError
from infrastructure.persistence.navidrome_folder_preferences_store import (
    NavidromeFolderPreference,
    NavidromeFolderPreferencesStore,
)
from repositories.protocols.navidrome import NavidromeRepositoryProtocol


class NavidromeFolderScope(msgspec.Struct, frozen=True):
    mode: str
    folder_ids: tuple[str, ...] = ()

    @property
    def cache_segment(self) -> str:
        if self.mode == "all":
            return "all"
        if not self.folder_ids:
            return "selected-empty"
        digest = hashlib.sha256("\0".join(self.folder_ids).encode()).hexdigest()[:20]
        return f"selected-{digest}"


class NavidromeFolderResolution(msgspec.Struct, frozen=True):
    preference: NavidromeFolderPreference
    scope: NavidromeFolderScope
    available_folders: tuple[tuple[str, str], ...] = ()
    stale_folder_ids: tuple[str, ...] = ()
    source_available: bool = True


class NavidromeFolderScopeService:
    def __init__(
        self,
        store: NavidromeFolderPreferencesStore,
        repository: NavidromeRepositoryProtocol,
    ) -> None:
        self._store = store
        self._repository = repository

    async def resolve(self, user_id: str) -> NavidromeFolderResolution:
        preference = await self._store.get(user_id)
        try:
            folders = await self._repository.get_music_folders()
        except (ExternalServiceError, CircuitOpenError):
            return NavidromeFolderResolution(
                preference=preference,
                scope=NavidromeFolderScope(
                    preference.mode,
                    preference.selected_folder_ids if preference.mode == "selected" else (),
                ),
                source_available=False,
            )
        available = tuple((folder.id, folder.name) for folder in folders)
        available_ids = {folder_id for folder_id, _ in available}
        identity_matches = (
            preference.server_identity is None
            or preference.server_identity == self._repository.server_identity
        )
        if preference.mode == "all":
            scope = NavidromeFolderScope("all")
            stale = ()
        elif identity_matches:
            scope = NavidromeFolderScope(
                "selected",
                tuple(
                    folder_id
                    for folder_id in preference.selected_folder_ids
                    if folder_id in available_ids
                ),
            )
            stale = tuple(
                folder_id
                for folder_id in preference.selected_folder_ids
                if folder_id not in available_ids
            )
        else:
            scope = NavidromeFolderScope("selected")
            stale = preference.selected_folder_ids
        return NavidromeFolderResolution(
            preference=preference,
            scope=scope,
            available_folders=available,
            stale_folder_ids=stale,
        )

    async def save(
        self, user_id: str, *, mode: str, selected_folder_ids: list[str]
    ) -> NavidromeFolderResolution:
        if mode == "all":
            if selected_folder_ids:
                raise ValueError("All folders cannot include selected folder IDs")
            await self._store.set(user_id, mode="all")
            return await self.resolve(user_id)
        if mode != "selected":
            raise ValueError("Invalid folder preference mode")
        if not selected_folder_ids:
            raise ValueError("Select at least one music folder")
        if len(selected_folder_ids) != len(set(selected_folder_ids)):
            raise ValueError("Duplicate music folder IDs are not allowed")
        folders = await self._repository.get_music_folders()
        available_ids = {folder.id for folder in folders}
        unknown = sorted(set(selected_folder_ids) - available_ids)
        if unknown:
            raise ValueError("One or more selected music folders are unavailable")
        await self._store.set(
            user_id,
            mode="selected",
            selected_folder_ids=tuple(selected_folder_ids),
            server_identity=self._repository.server_identity,
        )
        return await self.resolve(user_id)
