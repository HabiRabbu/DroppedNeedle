"""Regression tests for the one-time Lidarr-era config migration.

`migrate_legacy_config()` runs on every boot (FastAPI lifespan). It must:
- back up ALL removed legacy keys into `_legacy_lidarr` without data loss,
- be idempotent (never clobber an existing backup or re-migrate),
- no-op on a clean config or a missing file.
"""

import json
from types import SimpleNamespace

import core.config as config_module
from core.config import migrate_legacy_config

_LEGACY = {
    "lidarr_url": "http://old-lidarr:8686",
    "lidarr_api_key": "secret-key",
    "lidarr_timeout": 30,
    "quality_profile_id": 1,
    "metadata_profile_id": 2,
    "root_folder_path": "/music",
}


def _point_config_at(monkeypatch, path):
    monkeypatch.setattr(
        config_module, "get_settings", lambda: SimpleNamespace(config_file_path=path)
    )


def _write(path, data):
    path.write_text(json.dumps(data))


def _read(path):
    return json.loads(path.read_text())


def test_migrates_all_legacy_keys_losslessly(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    _write(path, {**_LEGACY, "jellyfin_url": "http://jelly:8096"})
    _point_config_at(monkeypatch, path)

    migrate_legacy_config()

    result = _read(path)
    # every legacy key is preserved in the backup (no silent data loss)
    assert result["_legacy_lidarr"] == {
        "url": "http://old-lidarr:8686",
        "api_key": "secret-key",
        "timeout": 30,
        "quality_profile_id": 1,
        "metadata_profile_id": 2,
        "root_folder_path": "/music",
    }
    # legacy keys are dropped from the active config
    for key in _LEGACY:
        assert key not in result
    # unrelated keys are untouched
    assert result["jellyfin_url"] == "http://jelly:8096"


def test_idempotent_does_not_clobber_existing_backup(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    _write(path, dict(_LEGACY))
    _point_config_at(monkeypatch, path)

    migrate_legacy_config()
    first = _read(path)["_legacy_lidarr"]
    migrate_legacy_config()  # second boot
    second = _read(path)["_legacy_lidarr"]

    assert first == second
    assert second["url"] == "http://old-lidarr:8686"  # not reset to None


def test_noop_on_clean_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    _write(path, {"jellyfin_url": "http://jelly:8096"})
    _point_config_at(monkeypatch, path)

    migrate_legacy_config()

    result = _read(path)
    assert "_legacy_lidarr" not in result
    assert result == {"jellyfin_url": "http://jelly:8096"}


def test_noop_when_config_file_missing(tmp_path, monkeypatch):
    path = tmp_path / "does-not-exist.json"
    _point_config_at(monkeypatch, path)

    migrate_legacy_config()  # must not raise

    assert not path.exists()
