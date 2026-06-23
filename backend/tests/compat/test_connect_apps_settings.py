"""T0.2 - ConnectAppsSettings persistence + enablement guard."""

from pathlib import Path

import msgspec
import pytest

from api.compat.common.enablement import (
    ensure_jellyfin_enabled,
    ensure_subsonic_enabled,
    is_jellyfin_enabled,
    is_subsonic_enabled,
)
from api.v1.schemas.settings import ConnectAppsSettings
from core.config import Settings
from core.exceptions import JellyfinError, SubsonicError
from services.preferences_service import PreferencesService


@pytest.fixture
def prefs(tmp_path: Path) -> PreferencesService:
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    return PreferencesService(settings)


def test_defaults_protocols_off_and_local_only():
    s = ConnectAppsSettings()
    assert s.subsonic_enabled is False
    assert s.jellyfin_enabled is False
    assert s.transcoding_enabled is True
    assert s.transcode_default_format == "mp3"
    assert s.transcode_max_bitrate_kbps == 320
    assert s.advertise_server_name == "DroppedNeedle"
    assert s.advertise_server_version == "10.10.6"
    assert s.discover_mode == "local-only"


def test_get_returns_defaults_on_fresh_install(prefs: PreferencesService):
    s = prefs.get_connect_apps_settings()
    assert s.subsonic_enabled is False and s.jellyfin_enabled is False
    assert s.discover_mode == "local-only"


def test_round_trip_including_discover_mode(prefs: PreferencesService):
    prefs.save_connect_apps_settings(
        ConnectAppsSettings(
            subsonic_enabled=True,
            jellyfin_enabled=True,
            transcoding_enabled=False,
            transcode_default_format="opus",
            transcode_max_bitrate_kbps=192,
            advertise_server_version="10.11.0",
            discover_mode="lazy-mb",
        )
    )
    s = prefs.get_connect_apps_settings()
    assert s.subsonic_enabled is True
    assert s.jellyfin_enabled is True
    assert s.transcoding_enabled is False
    assert s.transcode_default_format == "opus"
    assert s.transcode_max_bitrate_kbps == 192
    assert s.advertise_server_version == "10.11.0"
    assert s.discover_mode == "lazy-mb"


def test_persist_across_instances(tmp_path: Path):
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    PreferencesService(settings).save_connect_apps_settings(
        ConnectAppsSettings(subsonic_enabled=True, discover_mode="use-scrobble-targets")
    )
    reloaded = PreferencesService(settings).get_connect_apps_settings()
    assert reloaded.subsonic_enabled is True
    assert reloaded.discover_mode == "use-scrobble-targets"


def test_invalid_discover_mode_rejected():
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"discover_mode": "bogus"}, type=ConnectAppsSettings)


def test_invalid_transcode_format_rejected():
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"transcode_default_format": "flac"}, type=ConnectAppsSettings)


def test_invalid_bitrate_rejected():
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"transcode_max_bitrate_kbps": 16}, type=ConnectAppsSettings)


def test_enablement_guard_disabled_by_default():
    s = ConnectAppsSettings()
    assert is_subsonic_enabled(s) is False
    assert is_jellyfin_enabled(s) is False
    with pytest.raises(SubsonicError) as si:
        ensure_subsonic_enabled(s)
    assert si.value.code == 0
    with pytest.raises(JellyfinError) as ji:
        ensure_jellyfin_enabled(s)
    assert ji.value.status == 404


def test_enablement_guard_passes_when_enabled():
    s = ConnectAppsSettings(subsonic_enabled=True, jellyfin_enabled=True)
    assert is_subsonic_enabled(s) is True and is_jellyfin_enabled(s) is True
    ensure_subsonic_enabled(s)
    ensure_jellyfin_enabled(s)
