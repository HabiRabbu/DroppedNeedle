"""Provider-neutral genre candidates and projection results."""

from __future__ import annotations

from typing import Literal

import msgspec

GenreProvider = Literal[
    "musicbrainz", "listenbrainz", "lastfm", "existing_local", "override"
]


class GenreCandidate(msgspec.Struct, frozen=True, kw_only=True):
    display_name: str
    folded_name: str
    provider: GenreProvider
    provider_entity: str
    genre_mbid: str | None = None
    count: int | None = None
    weight: int | None = None
    curated: bool = False
    passed_gate: bool = False
    canonicalization_path: tuple[str, ...] = ()
    fetched_at: float | None = None
    source_document_revision: str | None = None


class GenreProjection(msgspec.Struct, frozen=True, kw_only=True):
    genres: tuple[GenreCandidate, ...]
    deferred_sources: tuple[str, ...] = ()
    preserved_existing: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(value.display_name for value in self.genres)
