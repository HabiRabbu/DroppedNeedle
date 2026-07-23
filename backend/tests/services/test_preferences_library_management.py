import json
from pathlib import Path

import msgspec
import pytest

from api.v1.schemas.library_management import (
    LEGACY_NAMING_PROFILE_ID,
    LEGACY_NAMING_SCRIPT_ID,
    LibraryManagementSettings,
)
from api.v1.schemas.settings import ACOUSTID_KEY_MASK
from core.config import Settings
from core.exceptions import ConfigurationError, StaleRevisionError
from infrastructure.crypto import encrypt
from services.preferences_service import PreferencesService


def _preferences(tmp_path: Path, payload: dict) -> PreferencesService:
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    settings.config_file_path.write_text(json.dumps(payload), encoding="utf-8")
    return PreferencesService(settings)


def test_management_migration_is_inert_idempotent_and_keeps_legacy_template(
    tmp_path: Path,
) -> None:
    template = "{albumartist}/{album}/{disc:02d}{track:02d} - {title}.{ext}"
    prefs = _preferences(
        tmp_path,
        {
            "library_settings": {
                "library_paths": [str(tmp_path / "Music")],
                "naming_template": template,
            }
        },
    )

    first = prefs.get_library_management_settings()
    first_text = prefs._config_path.read_text(encoding="utf-8")
    second = prefs.get_library_management_settings()

    legacy_script = next(
        value for value in first.naming_scripts if value.id == LEGACY_NAMING_SCRIPT_ID
    )
    legacy_profile = next(
        value for value in first.profiles if value.id == LEGACY_NAMING_PROFILE_ID
    )
    assert legacy_script.source == template
    assert legacy_profile.organization.naming_script_id == legacy_script.id
    assert first.root_assignments == []
    assert second.settings_revision == first.settings_revision
    assert prefs._config_path.read_text(encoding="utf-8") == first_text
    stored = json.loads(first_text)["library_management"]
    assert stored["root_assignments"] == []


def test_management_save_uses_revision_compare_and_swap(tmp_path: Path) -> None:
    prefs = _preferences(tmp_path, {})
    current = prefs.get_library_management_settings()
    update = prefs.get_library_management_settings_raw()
    update.undo_retention_days = 120
    update.recycle_bin_path = str(tmp_path / "Recycle")

    saved = prefs.save_library_management_settings_if_current(
        update,
        expected_settings_revision=current.settings_revision,
    )

    assert saved.undo_retention_days == 120
    assert saved.recycle_bin_path == str(tmp_path / "Recycle")
    assert saved.settings_revision != current.settings_revision
    with pytest.raises(StaleRevisionError):
        prefs.save_library_management_settings_if_current(
            update,
            expected_settings_revision=current.settings_revision,
        )


def test_management_save_round_trips_every_nested_group_without_activation(
    tmp_path: Path,
) -> None:
    prefs = _preferences(tmp_path, {})
    current = prefs.get_library_management_settings()
    update = prefs.get_library_management_settings_raw()
    profile = update.profiles[0]
    profile.metadata.artist_credits.translate_names = True
    profile.metadata.artist_credits.preferred_locales = ["en-GB", "ja"]
    profile.genres.maximum_count = 12
    profile.artwork.external_format = "png"
    profile.organization.compatibility.maximum_path_length = 1024
    profile.file_behavior.preserve_permissions = False
    profile.enrichment.lyrics.write_synced = False
    profile.notification.refresh_external_servers = True
    update.external_refresh.plex_enabled = True

    prefs.save_library_management_settings_if_current(
        update,
        expected_settings_revision=current.settings_revision,
    )
    saved = prefs.get_library_management_settings_raw()
    saved_profile = next(value for value in saved.profiles if value.id == profile.id)

    assert saved_profile.metadata.artist_credits.preferred_locales == ["en-GB", "ja"]
    assert saved_profile.genres.maximum_count == 12
    assert saved_profile.artwork.external_format == "png"
    assert saved_profile.organization.compatibility.maximum_path_length == 1024
    assert saved_profile.file_behavior.preserve_permissions is False
    assert saved_profile.enrichment.lyrics.write_synced is False
    assert saved_profile.notification.refresh_external_servers is True
    assert saved.external_refresh.plex_enabled is True
    assert saved.root_assignments == []


def test_management_save_does_not_replace_masked_library_secret(tmp_path: Path) -> None:
    encrypted_key = encrypt("acoustid-secret")
    prefs = _preferences(
        tmp_path,
        {
            "library_settings": {
                "library_paths": [str(tmp_path / "Music")],
                "acoustid_api_key": encrypted_key,
            }
        },
    )
    assert prefs.get_typed_library_settings().acoustid_api_key == ACOUSTID_KEY_MASK
    current = prefs.get_library_management_settings()

    prefs.save_library_management_settings_if_current(
        prefs.get_library_management_settings_raw(),
        expected_settings_revision=current.settings_revision,
    )

    assert prefs.get_typed_library_settings_raw().acoustid_api_key == "acoustid-secret"


def test_invalid_stored_management_settings_fail_closed(tmp_path: Path) -> None:
    prefs = _preferences(
        tmp_path,
        {
            "library_management": {
                "schema_version": 999,
                "profiles": [],
                "default_profile_id": "",
            }
        },
    )

    with pytest.raises(ConfigurationError, match="invalid"):
        prefs.get_library_management_settings()


def test_invalid_stored_management_script_fails_closed(tmp_path: Path) -> None:
    prefs = _preferences(tmp_path, {})
    prefs.get_library_management_settings()
    payload = json.loads(prefs._config_path.read_text(encoding="utf-8"))
    payload["library_management"]["naming_scripts"][0]["source"] = (
        "{environment('HOME')}"
    )

    fresh = _preferences(tmp_path, payload)

    with pytest.raises(ConfigurationError, match="invalid"):
        fresh.get_library_management_settings()


def test_invalid_management_script_save_is_a_configuration_error(
    tmp_path: Path,
) -> None:
    prefs = _preferences(tmp_path, {})
    current = prefs.get_library_management_settings()
    update = prefs.get_library_management_settings_raw()
    update.naming_scripts[0].source = "{__import__('os')}"

    with pytest.raises(ConfigurationError, match="Unknown safe function"):
        prefs.save_library_management_settings_if_current(
            update,
            expected_settings_revision=current.settings_revision,
        )


def test_recycle_bin_path_must_be_absolute(tmp_path: Path) -> None:
    prefs = _preferences(tmp_path, {})
    current = prefs.get_library_management_settings()
    update = prefs.get_library_management_settings_raw()
    update.recycle_bin_path = "relative/recycle"

    with pytest.raises(ConfigurationError, match="absolute path"):
        prefs.save_library_management_settings_if_current(
            update,
            expected_settings_revision=current.settings_revision,
        )


def test_raw_management_settings_are_a_detached_typed_copy(tmp_path: Path) -> None:
    prefs = _preferences(tmp_path, {})
    raw = prefs.get_library_management_settings_raw()

    assert isinstance(raw, LibraryManagementSettings)
    assert isinstance(
        msgspec.to_builtins(raw)["profiles"],
        list,
    )
    raw.profiles.clear()
    assert prefs.get_library_management_settings().profiles
