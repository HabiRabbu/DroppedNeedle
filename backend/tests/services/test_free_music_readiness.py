"""`is_download_source_ready()` is the single source of truth for "can the user
acquire". It gates Home and Discover surfaces and the Request button, so
widening it for Free Music (D24) gets its own test."""

import json
from types import SimpleNamespace

import pytest

from services.preferences_service import PreferencesService


def _prefs(tmp_path, config: dict) -> PreferencesService:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return PreferencesService(SimpleNamespace(config_file_path=path))


def test_free_music_alone_makes_the_user_able_to_acquire(tmp_path):
    prefs = _prefs(tmp_path, {})  # nothing configured; Free Music defaults on

    assert prefs.is_builtin_download_ready() is False
    assert prefs.is_download_source_ready() is True


def test_disabling_free_music_with_no_client_leaves_no_source(tmp_path):
    prefs = _prefs(tmp_path, {"free_music": {"enabled": False}})

    assert prefs.is_download_source_ready() is False


def test_free_music_defaults_to_enabled_and_flac(tmp_path):
    """It is enabled by default on purpose: the lawful use it demonstrates is
    what makes having a download engine defensible (D23/D24)."""
    settings = _prefs(tmp_path, {}).get_free_music_settings()

    assert settings.enabled is True
    assert settings.preferred_format == "flac"


def test_an_unknown_preferred_format_falls_back_to_flac(tmp_path):
    settings = _prefs(tmp_path, {"free_music": {"preferred_format": "wav"}}).get_free_music_settings()
    assert settings.preferred_format == "flac"
