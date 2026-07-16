import json
from pathlib import Path

import pytest

from api.v1.schemas.library_policies import (
    LibraryPathPolicyRule,
    LibraryRootSettings,
    TypedLibrarySettings,
)
from api.v1.schemas.settings import ACOUSTID_KEY_MASK
from core.config import Settings
from core.exceptions import ConfigurationError
from infrastructure.crypto import encrypt
from services.preferences_service import PreferencesService


def _preferences(tmp_path: Path, payload: dict) -> PreferencesService:
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    settings.config_file_path.write_text(json.dumps(payload), encoding="utf-8")
    return PreferencesService(settings)


def test_legacy_paths_migrate_once_with_stable_ids_and_secret(tmp_path: Path) -> None:
    music = tmp_path / "Music"
    music.mkdir()
    encrypted = encrypt("acoustid-secret")
    prefs = _preferences(
        tmp_path,
        {
            "library_settings": {
                "library_paths": [str(music)],
                "staging_path": "",
                "naming_template": "{title}.{ext}",
                "acoustid_api_key": encrypted,
            }
        },
    )

    first = prefs.get_typed_library_settings()
    first_text = prefs._config_path.read_text(encoding="utf-8")
    second = prefs.get_typed_library_settings()

    assert first.library_roots == second.library_roots
    assert prefs.get_legacy_library_paths() == [str(music)]
    assert prefs.get_library_settings().library_paths == [str(music)]
    assert first.library_roots[0].policy == "automatic"
    assert first.library_roots[0].rules == []
    assert first.acoustid_api_key == ACOUSTID_KEY_MASK
    assert prefs.get_typed_library_settings_raw().acoustid_api_key == "acoustid-secret"
    assert prefs._config_path.read_text(encoding="utf-8") == first_text
    stored = json.loads(first_text)["library_settings"]
    assert "library_paths" not in stored
    assert stored["library_roots"][0]["id"] == first.library_roots[0].id


def test_legacy_overlap_blocks_migration(tmp_path: Path) -> None:
    outer = tmp_path / "Music"
    inner = outer / "Nested"
    inner.mkdir(parents=True)
    prefs = _preferences(
        tmp_path,
        {"library_settings": {"library_paths": [str(outer), str(inner)]}},
    )

    with pytest.raises(ConfigurationError):
        prefs.get_typed_library_settings()


def test_typed_save_preserves_ids_and_masked_secret(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    prefs = _preferences(tmp_path, {})
    original = prefs.get_typed_library_settings()
    root_id = original.library_roots[0].id
    prefs.save_typed_library_settings(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(
                    id=root_id,
                    path=original.library_roots[0].path,
                    label="Music",
                    rules=[
                        LibraryPathPolicyRule(
                            id="rule-1",
                            relative_path="Prepared",
                            policy="local_metadata",
                        )
                    ],
                )
            ],
            acoustid_api_key="secret",
        )
    )
    prefs.save_typed_library_settings(
        TypedLibrarySettings(
            library_roots=prefs.get_typed_library_settings().library_roots,
            acoustid_api_key=ACOUSTID_KEY_MASK,
        )
    )

    saved = prefs.get_typed_library_settings_raw()
    assert saved.library_roots[0].id == root_id
    assert saved.library_roots[0].rules[0].id == "rule-1"
    assert saved.acoustid_api_key == "secret"


def test_existing_root_and_rule_paths_are_immutable(tmp_path: Path) -> None:
    prefs = _preferences(tmp_path, {})
    current = prefs.get_typed_library_settings()
    root = current.library_roots[0]
    with pytest.raises(ConfigurationError, match="cannot be moved"):
        prefs.save_typed_library_settings(
            TypedLibrarySettings(
                library_roots=[
                    LibraryRootSettings(
                        id=root.id, path=str(tmp_path / "Elsewhere"), label=root.label
                    )
                ]
            )
        )
