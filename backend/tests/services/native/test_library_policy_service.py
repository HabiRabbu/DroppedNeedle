import sqlite3
import threading
from pathlib import Path

import pytest

from api.v1.schemas.library_policies import (
    LibraryPathPolicyRule,
    LibraryPolicyImpactRequest,
    LibraryRootSettings,
    TypedLibrarySettings,
)
from core.config import Settings
from core.exceptions import ConfigurationError, StaleRevisionError
from core.task_registry import TaskRegistry
from infrastructure.persistence.library_db import LibraryDB
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_policy_service import LibraryPolicyService
from services.preferences_service import PreferencesService


def _build(tmp_path: Path):
    root = tmp_path / "Music"
    root.mkdir()
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    preferences = PreferencesService(settings)
    preferences.save_typed_library_settings(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(id="root-1", path=str(root), label="Music")
            ]
        )
    )
    database = LibraryDB(tmp_path / "library.db", threading.Lock())
    cached: LibraryPolicyResolver | None = None

    def get_resolver() -> LibraryPolicyResolver:
        nonlocal cached
        if cached is None:
            cached = LibraryPolicyResolver(preferences.get_typed_library_settings())
        return cached

    def clear_resolver() -> None:
        nonlocal cached
        cached = None

    service = LibraryPolicyService(preferences, database, get_resolver, clear_resolver)
    return service, preferences, database, root


def test_save_returns_pending_impact_without_starting_work(tmp_path: Path) -> None:
    service, preferences, _database, root = _build(tmp_path)
    TaskRegistry.get_instance().reset()
    current_revision = service.get_settings().policy_revision
    response = service.save_settings(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(
                    id="root-1",
                    path=str(root),
                    label="Music",
                    policy="local_metadata",
                )
            ]
        ),
        expected_policy_revision=current_revision,
    )

    assert response.reconciliation_required is True
    assert response.affected_scope_ids == ["root-1"]
    assert response.actions_applied == [
        "Settings saved. No scan or reconciliation was started."
    ]
    assert (
        preferences.get_typed_library_settings().library_roots[0].policy
        == "local_metadata"
    )
    assert TaskRegistry.get_instance().get_all() == {}


def test_impact_marks_stale_and_reports_exclusion(tmp_path: Path) -> None:
    service, _preferences, _database, root = _build(tmp_path)
    impact = service.preview_impact(
        LibraryPolicyImpactRequest(
            expected_policy_revision="stale",
            settings=TypedLibrarySettings(
                library_roots=[
                    LibraryRootSettings(
                        id="root-1",
                        path=str(root),
                        label="Music",
                        policy="excluded",
                    )
                ]
            ),
        )
    )

    assert impact.stale is True
    assert impact.affected_scope_ids == ["root-1"]
    assert impact.content_will_become_unavailable is True
    assert impact.queued_work_will_be_cancelled is True


def test_removed_rule_reconciles_its_previous_path_with_inherited_policy(
    tmp_path: Path,
) -> None:
    service, _preferences, _database, root = _build(tmp_path)
    with_rule = TypedLibrarySettings(
        library_roots=[
            LibraryRootSettings(
                id="root-1",
                path=str(root),
                label="Music",
                policy="automatic",
                rules=[
                    LibraryPathPolicyRule(
                        id="rule-1",
                        relative_path="Prepared",
                        policy="excluded",
                    )
                ],
            )
        ]
    )
    service.save_settings(
        with_rule,
        expected_policy_revision=service.get_settings().policy_revision,
    )

    scopes = service.preview_scopes(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(
                    id="root-1",
                    path=str(root),
                    label="Music",
                    policy="automatic",
                )
            ]
        )
    )

    assert len(scopes) == 1
    assert scopes[0].scope_id == "rule-1"
    assert scopes[0].relative_path == "Prepared"
    assert scopes[0].effective_policy == "automatic"
    assert scopes[0].root_path == str(root)


def test_removed_root_keeps_a_frozen_excluded_scope(tmp_path: Path) -> None:
    service, _preferences, _database, root = _build(tmp_path)

    scopes = service.preview_scopes(TypedLibrarySettings(library_roots=[]))

    assert len(scopes) == 1
    assert scopes[0].scope_id == "root-1"
    assert scopes[0].relative_path == "."
    assert scopes[0].effective_policy == "excluded"
    assert scopes[0].root_path == str(root)


def test_save_refuses_a_revision_that_changed_after_preview(tmp_path: Path) -> None:
    service, preferences, _database, root = _build(tmp_path)
    original = service.get_settings().policy_revision
    preferences.save_typed_library_settings(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(
                    id="root-1",
                    path=str(root),
                    label="Changed elsewhere",
                    policy="local_metadata",
                )
            ]
        )
    )

    with pytest.raises(StaleRevisionError, match="settings changed"):
        service.save_settings(
            TypedLibrarySettings(
                library_roots=[
                    LibraryRootSettings(id="root-1", path=str(root), label="Stale edit")
                ]
            ),
            expected_policy_revision=original,
        )

    assert preferences.get_typed_library_settings().library_roots[0].label == (
        "Changed elsewhere"
    )


@pytest.mark.asyncio
async def test_dry_run_maps_every_catalog_and_review_path_once(tmp_path: Path) -> None:
    service, _preferences, database, root = _build(tmp_path)
    catalog_path = root / "Artist" / "Album" / "01.flac"
    review_path = root / "Loose" / "02.flac"
    outside_path = tmp_path / "Outside" / "03.flac"
    with sqlite3.connect(database.db_path) as connection:
        connection.execute(
            "INSERT INTO library_files "
            "(id, track_number, track_title, album_title, file_path, file_size_bytes, "
            "file_mtime, file_format, source, confidence, imported_at) "
            "VALUES ('file-1', 1, 'Track', 'Album', ?, 1, 1, 'flac', "
            "'manual_review', 1, 1)",
            (str(catalog_path),),
        )
        connection.executemany(
            "INSERT INTO manual_review_queue (file_path, source, created_at) "
            "VALUES (?, 'text_match', 1)",
            [(str(review_path),), (str(outside_path),)],
        )
        connection.commit()

    report = await service.dry_run_path_mapping()

    assert report.source_count == 3
    assert report.mapped_count == 2
    assert report.out_of_root_count == 1
    assert report.ambiguous_count == 0
    assert report.blocking is True
    mapped = [item for item in report.items if item.error is None]
    assert {item.relative_path for item in mapped} == {
        "Artist/Album/01.flac",
        "Loose/02.flac",
    }
    with pytest.raises(ConfigurationError, match="Catalog import is blocked"):
        service.require_catalog_import_mapping(report)


def test_policy_tree_reports_nested_inheritance_and_availability(
    tmp_path: Path,
) -> None:
    service, _preferences, _database, root = _build(tmp_path)
    service.save_settings(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(
                    id="root-1",
                    path=str(root),
                    label="Music",
                    rules=[
                        LibraryPathPolicyRule(
                            id="rule-1",
                            relative_path="Prepared",
                            policy="local_metadata",
                        )
                    ],
                )
            ]
        ),
        expected_policy_revision=service.get_settings().policy_revision,
    )

    tree = service.policy_tree()

    assert tree.roots[0].inherited_from_id == "root-1"
    assert tree.roots[0].children[0].inherited_from_id == "rule-1"
    assert tree.roots[0].children[0].available is False
