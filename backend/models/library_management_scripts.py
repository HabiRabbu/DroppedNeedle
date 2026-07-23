"""Results and attribution for bounded Library Management scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import msgspec

from models.audio_metadata import AudioMetadataDocument

ScriptMutationOperation = Literal["set", "append", "delete"]


class CustomTagValue(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    values: tuple[str, ...]


class TaggingTransformation(msgspec.Struct, frozen=True, kw_only=True):
    script_id: str
    script_name: str
    operation: ScriptMutationOperation
    target: str
    before: str | int | bool | tuple[str, ...] | None
    after: str | int | bool | tuple[str, ...] | None
    line: int
    column: int
    skipped_reason: str | None = None


class TaggingScriptResult(msgspec.Struct, frozen=True, kw_only=True):
    metadata: AudioMetadataDocument
    custom_tags: tuple[CustomTagValue, ...]
    transformations: tuple[TaggingTransformation, ...]


class NamingRenderResult(msgspec.Struct, frozen=True, kw_only=True):
    relative_path: str
    collision_key: str
    rendered_characters: int

    def as_path(self) -> Path:
        return Path(self.relative_path)
