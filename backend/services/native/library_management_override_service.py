"""Validated persistent override CRUD; this service never writes audio files."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable

from core.exceptions import ResourceNotFoundError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_management import LibraryManagementOverride
from services.native.effective_metadata_projection_service import (
    normalize_managed_field_value,
)
from services.native.managed_field_registry import get_managed_field


class LibraryManagementOverrideService:
    def __init__(
        self,
        store: NativeLibraryStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._clock = clock

    async def save(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        subject_revision: int,
        field_name: str,
        mode: str,
        value: object = None,
        actor_user_id: str | None = None,
        reason: str | None = None,
        override_id: str | None = None,
        expected_row_revision: int | None = None,
    ) -> LibraryManagementOverride:
        definition = get_managed_field(field_name)
        if definition is None or not definition.allow_override:
            raise ValidationError("That field cannot be overridden.")
        if subject_kind not in {"album", "track"} or definition.scope != subject_kind:
            raise ValidationError(
                f"{field_name} requires a {definition.scope}-level override."
            )
        if mode not in {"replace", "preserve", "clear"}:
            raise ValidationError("Unknown management override mode.")
        if subject_revision < 1:
            raise ValidationError("The override subject revision is invalid.")
        if override_id is None and expected_row_revision is not None:
            raise ValidationError(
                "A new override cannot have an existing row revision."
            )
        if override_id is not None and expected_row_revision is None:
            raise ValidationError("Updating an override requires its current revision.")

        normalized = None
        if mode == "replace":
            normalized = normalize_managed_field_value(definition, value)
            if normalized is None:
                raise ValidationError("Use explicit clear to remove a managed value.")
        now = self._clock()
        return await self._store.save_management_override(
            LibraryManagementOverride(
                id=override_id or str(uuid.uuid4()),
                subject_kind=subject_kind,
                local_album_id=subject_id if subject_kind == "album" else None,
                local_track_id=subject_id if subject_kind == "track" else None,
                field_name=field_name,
                value_json=json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                mode=mode,
                actor_user_id=actor_user_id,
                reason=reason,
                subject_revision=subject_revision,
                created_at=now,
                updated_at=now,
            ),
            expected_row_revision=expected_row_revision,
        )

    async def reset(
        self,
        *,
        override_id: str,
        subject_kind: str,
        subject_id: str,
        expected_row_revision: int,
    ) -> None:
        current = await self._store.get_management_override(override_id)
        if current is None:
            raise ResourceNotFoundError("Management override not found.")
        current_subject = (
            current.local_album_id
            if current.subject_kind == "album"
            else current.local_track_id
        )
        if current.subject_kind != subject_kind or current_subject != subject_id:
            raise ResourceNotFoundError("Management override not found.")
        await self._store.delete_management_override(
            override_id, expected_row_revision=expected_row_revision
        )

    async def list_for_subject(
        self, *, subject_kind: str, subject_id: str
    ) -> tuple[list[LibraryManagementOverride], str]:
        if subject_kind not in {"album", "track"}:
            raise ValidationError("Unknown management override subject.")
        return await self._store.list_management_overrides(
            subject_kind=subject_kind, subject_id=subject_id
        )
