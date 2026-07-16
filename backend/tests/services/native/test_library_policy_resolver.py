from pathlib import Path

import pytest

from api.v1.schemas.library_policies import (
    LibraryPathPolicyRule,
    LibraryRootSettings,
    TypedLibrarySettings,
)
from core.exceptions import ConfigurationError
from services.native.library_policy_resolver import LibraryPolicyResolver


def _settings(root: Path, *, rules=None, policy="automatic", staging=""):
    return TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root-1",
                path=str(root),
                label="Music",
                policy=policy,
                rules=rules or [],
            )
        ],
        staging_path=staging,
    )


def test_most_specific_rule_wins_by_complete_path_segment(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    (root / "Jazz" / "Live").mkdir(parents=True)
    (root / "Jazz-Funk").mkdir()
    resolver = LibraryPolicyResolver(
        _settings(
            root,
            rules=[
                LibraryPathPolicyRule(
                    id="rule-jazz", relative_path="Jazz", policy="local_metadata"
                ),
                LibraryPathPolicyRule(
                    id="rule-live", relative_path="Jazz/Live", policy="excluded"
                ),
            ],
        )
    )

    jazz = resolver.resolve(root / "Jazz" / "track.flac")
    live = resolver.resolve(root / "Jazz" / "Live" / "track.flac")
    jazz_funk = resolver.resolve(root / "Jazz-Funk" / "track.flac")

    assert jazz and (jazz.policy, jazz.inherited_from_id) == (
        "local_metadata",
        "rule-jazz",
    )
    assert live and (live.policy, live.inherited_from_id) == ("excluded", "rule-live")
    assert jazz_funk and jazz_funk.policy == "automatic"


@pytest.mark.parametrize(
    "relative_path", ["../escape", "/absolute", "C:/drive", "bad\\path"]
)
def test_rule_rejects_unsafe_paths(tmp_path: Path, relative_path: str) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    with pytest.raises(ConfigurationError):
        LibraryPolicyResolver(
            _settings(
                root,
                rules=[
                    LibraryPathPolicyRule(
                        id="rule-1",
                        relative_path=relative_path,
                        policy="excluded",
                    )
                ],
            )
        )


def test_rule_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    outside = tmp_path / "Outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="escapes"):
        LibraryPolicyResolver(
            _settings(
                root,
                rules=[
                    LibraryPathPolicyRule(
                        id="rule-1", relative_path="escape", policy="excluded"
                    )
                ],
            )
        )


def test_unavailable_root_and_rule_are_warnings(tmp_path: Path) -> None:
    resolver = LibraryPolicyResolver(
        _settings(
            tmp_path / "offline",
            rules=[
                LibraryPathPolicyRule(
                    id="rule-1", relative_path="prepared", policy="local_metadata"
                )
            ],
        )
    )

    assert len(resolver.warnings) == 2
    assert all("not currently available" in warning for warning in resolver.warnings)


def test_duplicate_overlap_staging_and_case_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    nested = root / "Nested"
    nested.mkdir(parents=True)
    with pytest.raises(ConfigurationError, match="overlap"):
        LibraryPolicyResolver(
            TypedLibrarySettings(
                library_roots=[
                    LibraryRootSettings(id="a", path=str(root), label="A"),
                    LibraryRootSettings(id="b", path=str(nested), label="B"),
                ]
            )
        )
    with pytest.raises(ConfigurationError, match="staging"):
        LibraryPolicyResolver(_settings(nested, staging=str(root)))

    resolver = LibraryPolicyResolver(_settings(root))
    assert resolver.resolve(tmp_path / "music" / "track.flac") is None


def test_revision_only_tracks_policy_input(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    first = LibraryPolicyResolver(_settings(root))
    relabelled = _settings(root)
    relabelled.library_roots[0].label = "Renamed"
    relabelled.acoustid_api_key = "secret"
    second = LibraryPolicyResolver(relabelled)
    excluded = LibraryPolicyResolver(_settings(root, policy="excluded"))

    assert first.policy_revision == second.policy_revision
    assert first.policy_revision != excluded.policy_revision
