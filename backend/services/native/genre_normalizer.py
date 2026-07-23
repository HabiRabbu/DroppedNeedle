"""Pure deterministic canonical genre normalization."""

from __future__ import annotations

import json
from pathlib import Path
import unicodedata

from api.v1.schemas.library_management import GenreManagementSettings
from core.exceptions import ConfigurationError
from models.library_management_genres import GenreCandidate


def fold_genre(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split()).casefold()


class GenreNormalizer:
    def __init__(self, asset_path: Path | None = None) -> None:
        self._asset_path = asset_path or (
            Path(__file__).resolve().parents[2]
            / "assets"
            / "library_management_genres.json"
        )
        try:
            payload = json.loads(self._asset_path.read_text(encoding="utf-8"))
            genres = payload["genres"]
            aliases = payload["aliases"]
            parents = payload["parents"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ConfigurationError(
                "The Library Management genre vocabulary is invalid."
            ) from error
        if (
            not isinstance(genres, list)
            or not isinstance(aliases, dict)
            or not isinstance(parents, dict)
        ):
            raise ConfigurationError(
                "The Library Management genre vocabulary is invalid."
            )
        self._display_by_folded = {
            fold_genre(value): unicodedata.normalize("NFC", value)
            for value in genres
            if isinstance(value, str) and fold_genre(value)
        }
        self._aliases = {
            fold_genre(source): fold_genre(target)
            for source, target in aliases.items()
            if isinstance(source, str) and isinstance(target, str)
        }
        self._parents = {
            fold_genre(child): fold_genre(parent)
            for child, parent in parents.items()
            if isinstance(child, str) and isinstance(parent, str)
        }
        if any(
            target not in self._display_by_folded for target in self._aliases.values()
        ):
            raise ConfigurationError(
                "A genre alias targets an unknown canonical genre."
            )
        if any(
            value not in self._display_by_folded
            for pair in self._parents.items()
            for value in pair
        ):
            raise ConfigurationError("The genre hierarchy contains an unknown genre.")
        self._validate_no_cycles()

    def _validate_no_cycles(self) -> None:
        for start in self._parents:
            seen: set[str] = set()
            current = start
            while current in self._parents:
                if current in seen:
                    raise ConfigurationError("The genre hierarchy contains a cycle.")
                seen.add(current)
                current = self._parents[current]

    @property
    def vocabulary_size(self) -> int:
        return len(self._display_by_folded)

    def normalize(
        self,
        candidate: GenreCandidate,
        settings: GenreManagementSettings,
        *,
        require_canonical_vocabulary: bool,
    ) -> GenreCandidate | None:
        folded = fold_genre(candidate.display_name)
        if not folded:
            return None
        profile_aliases = {
            fold_genre(value.source): fold_genre(value.target)
            for value in settings.aliases
        }
        if settings.canonicalize:
            folded = profile_aliases.get(folded, self._aliases.get(folded, folded))

        allowlist = {fold_genre(value) for value in settings.allowlist}
        denylist = {fold_genre(value) for value in settings.denylist}
        if folded in denylist or (allowlist and folded not in allowlist):
            return None
        if (
            require_canonical_vocabulary
            and folded not in self._display_by_folded
            and folded not in allowlist
        ):
            return None

        preferred = {
            fold_genre(value): unicodedata.normalize("NFC", value).strip()
            for value in settings.preferred_casing
        }
        display = preferred.get(
            folded,
            self._display_by_folded.get(
                folded,
                " ".join(unicodedata.normalize("NFC", candidate.display_name).split()),
            ),
        )
        path = [display]
        if settings.canonicalize:
            current = folded
            seen = {current}
            for _ in range(settings.maximum_ancestry_depth):
                parent = self._parents.get(current)
                if parent is None:
                    break
                if parent in seen:
                    raise ConfigurationError("The genre hierarchy contains a cycle.")
                seen.add(parent)
                path.append(self._display_by_folded[parent])
                current = parent

        return GenreCandidate(
            display_name=display,
            folded_name=folded,
            provider=candidate.provider,
            provider_entity=candidate.provider_entity,
            genre_mbid=candidate.genre_mbid,
            count=candidate.count,
            weight=candidate.weight,
            curated=candidate.curated,
            passed_gate=True,
            canonicalization_path=tuple(path),
            fetched_at=candidate.fetched_at,
            source_document_revision=candidate.source_document_revision,
        )
