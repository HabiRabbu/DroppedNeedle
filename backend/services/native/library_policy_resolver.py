"""Validation and segment-aware resolution for typed library roots."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import msgspec

from api.v1.schemas.library_policies import (
    LibraryIdentificationPolicy,
    LibraryPathPolicyRule,
    LibraryRootSettings,
    TypedLibrarySettings,
)
from core.exceptions import ConfigurationError


@dataclass(frozen=True)
class ResolvedLibraryPolicy:
    root_id: str
    relative_path: str
    policy: LibraryIdentificationPolicy
    inherited_from_id: str


def _canonical_root(path: str) -> Path:
    if not path.strip():
        raise ConfigurationError("A library root needs a path.")
    candidate = Path(os.path.normpath(path.strip()))
    if not candidate.is_absolute():
        raise ConfigurationError(f"Library root paths must be absolute: {path}")
    return candidate.resolve(strict=False)


def _normalise_rule_path(path: str) -> str:
    candidate = path.strip()
    if not candidate:
        raise ConfigurationError("A policy rule needs a directory path.")
    if "\\" in candidate:
        raise ConfigurationError("Policy rule paths must use forward slashes.")
    parsed = PurePosixPath(candidate)
    if (
        parsed.is_absolute()
        or (parsed.parts and parsed.parts[0].endswith(":"))
        or any(part in ("", ".", "..") for part in parsed.parts)
    ):
        raise ConfigurationError(
            f"Policy rule paths must stay inside their library root: {path}"
        )
    return parsed.as_posix()


class LibraryPolicyResolver:
    def __init__(self, settings: TypedLibrarySettings) -> None:
        self.settings, self.warnings = self._normalise_and_validate(settings)
        self.policy_revision = self._revision(self.settings)

    @staticmethod
    def _revision(settings: TypedLibrarySettings) -> str:
        payload = {
            "roots": [
                {
                    "id": root.id,
                    "path": root.path,
                    "policy": root.policy,
                    "rules": [
                        {
                            "id": rule.id,
                            "relative_path": rule.relative_path,
                            "policy": rule.policy,
                        }
                        for rule in root.rules
                    ],
                }
                for root in settings.library_roots
            ]
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _normalise_and_validate(
        cls, settings: TypedLibrarySettings
    ) -> tuple[TypedLibrarySettings, list[str]]:
        root_ids: set[str] = set()
        labels: set[str] = set()
        canonical_paths: list[tuple[str, Path]] = []
        roots: list[LibraryRootSettings] = []
        warnings: list[str] = []
        staging = (
            Path(settings.staging_path).resolve(strict=False)
            if settings.staging_path.strip()
            else None
        )

        for root in settings.library_roots:
            if not root.id.strip() or root.id in root_ids:
                raise ConfigurationError("Every library root needs a unique ID.")
            root_ids.add(root.id)
            label = root.label.strip()
            if not label or label.casefold() in labels:
                raise ConfigurationError("Every library root needs a unique label.")
            labels.add(label.casefold())
            canonical = _canonical_root(root.path)
            if staging is not None and canonical.is_relative_to(staging):
                raise ConfigurationError(
                    f"Library root {label} cannot be inside the staging directory."
                )
            for other_label, other in canonical_paths:
                if canonical == other:
                    raise ConfigurationError(
                        f"Library roots {other_label} and {label} use the same path."
                    )
                if canonical.is_relative_to(other) or other.is_relative_to(canonical):
                    raise ConfigurationError(
                        f"Library roots {other_label} and {label} overlap."
                    )
            canonical_paths.append((label, canonical))

            rule_ids: set[str] = set()
            rule_paths: set[str] = set()
            rules: list[LibraryPathPolicyRule] = []
            for rule in root.rules:
                if not rule.id.strip() or rule.id in rule_ids:
                    raise ConfigurationError(
                        f"Every policy rule under {label} needs a unique ID."
                    )
                rule_ids.add(rule.id)
                relative = _normalise_rule_path(rule.relative_path)
                path_key = (
                    relative
                    if os.path.normcase("A") != os.path.normcase("a")
                    else relative.casefold()
                )
                if path_key in rule_paths:
                    raise ConfigurationError(
                        f"Library root {label} has more than one rule for {relative}."
                    )
                rule_paths.add(path_key)
                resolved_rule = (
                    canonical / Path(*PurePosixPath(relative).parts)
                ).resolve(strict=False)
                if not resolved_rule.is_relative_to(canonical):
                    raise ConfigurationError(
                        f"Policy rule {relative} escapes library root {label}."
                    )
                if not resolved_rule.exists():
                    warnings.append(
                        f"Policy path {relative} under {label} is not currently available."
                    )
                rules.append(
                    LibraryPathPolicyRule(
                        id=rule.id, relative_path=relative, policy=rule.policy
                    )
                )
            rules.sort(
                key=lambda item: (
                    len(PurePosixPath(item.relative_path).parts),
                    item.relative_path,
                )
            )
            if not canonical.exists():
                warnings.append(f"Library root {label} is not currently available.")
            roots.append(
                LibraryRootSettings(
                    id=root.id,
                    path=str(canonical),
                    label=label,
                    policy=root.policy,
                    rules=rules,
                )
            )

        return (
            TypedLibrarySettings(
                library_roots=roots,
                staging_path=str(staging) if staging is not None else "",
                naming_template=settings.naming_template,
                acoustid_api_key=settings.acoustid_api_key,
            ),
            warnings,
        )

    def resolve(self, path: str | Path) -> ResolvedLibraryPolicy | None:
        candidate = Path(path).resolve(strict=False)
        matches: list[tuple[LibraryRootSettings, Path]] = []
        for root in self.settings.library_roots:
            root_path = Path(root.path)
            if candidate.is_relative_to(root_path):
                matches.append((root, root_path))
        if not matches:
            return None
        if len(matches) != 1:
            raise ConfigurationError(f"Path matches more than one library root: {path}")
        root, root_path = matches[0]
        relative = candidate.relative_to(root_path)
        relative_parts = relative.parts
        selected: LibraryPathPolicyRule | None = None
        for rule in root.rules:
            parts = PurePosixPath(rule.relative_path).parts
            if relative_parts[: len(parts)] == parts:
                selected = rule
        return ResolvedLibraryPolicy(
            root_id=root.id,
            relative_path=PurePosixPath(*relative_parts).as_posix(),
            policy=selected.policy if selected else root.policy,
            inherited_from_id=selected.id if selected else root.id,
        )

    def to_builtins(self) -> dict[str, object]:
        return msgspec.to_builtins(self.settings)
