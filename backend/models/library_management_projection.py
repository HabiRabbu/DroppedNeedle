"""Effective managed-field values and provenance."""

from __future__ import annotations

from typing import Any, Literal

import msgspec


FieldProjectionSource = Literal[
    "existing",
    "canonical",
    "enrichment",
    "transformation",
    "album_override",
    "track_override",
    "manual_override",
    "explicit_clear",
]


class EffectiveManagedField(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    value: Any
    source: FieldProjectionSource
    mode: str
    cleared: bool = False


class EffectiveMetadataProjection(msgspec.Struct, frozen=True, kw_only=True):
    fields: tuple[EffectiveManagedField, ...]
    scrub_unmanaged_tags: bool
    preserved_fields: tuple[str, ...]

    def value_for(self, name: str) -> Any:
        for field in self.fields:
            if field.name == name:
                return field.value
        raise KeyError(name)

    def field_for(self, name: str) -> EffectiveManagedField:
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)
