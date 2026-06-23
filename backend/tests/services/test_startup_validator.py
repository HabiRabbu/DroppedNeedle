"""Tests for StartupValidator (basic Phase 3 checks + Phase 4 fpcalc check)."""

import logging

import pytest

from core import startup_validator
from core.exceptions import ConfigurationError
from core.startup_validator import StartupValidator


def test_missing_library_path_raises(tmp_path):
    with pytest.raises(ConfigurationError):
        StartupValidator([tmp_path / "does-not-exist"], None).validate()


def test_existing_library_path_ok(tmp_path):
    # No raise when the path exists and no staging is configured.
    StartupValidator([tmp_path], None).validate()


def test_no_paths_warns_but_does_not_raise(tmp_path):
    StartupValidator([], None).validate()  # empty config is a warning, not fatal


def test_missing_staging_dir_is_auto_created(tmp_path):
    staging = tmp_path / "staging"
    assert not staging.exists()
    StartupValidator([tmp_path], staging).validate()
    assert staging.exists()


def test_staging_on_same_filesystem_ok(tmp_path):
    # tmp_path and its child share a device - no atomic-move error.
    staging = tmp_path / "staging"
    StartupValidator([tmp_path], staging).validate()
    assert staging.exists()


def test_missing_path_reported_before_staging(tmp_path):
    # A bad library path short-circuits before staging is touched.
    staging = tmp_path / "staging"
    with pytest.raises(ConfigurationError):
        StartupValidator([tmp_path / "missing"], staging).validate()
    assert not staging.exists()


def test_missing_fpcalc_warns_but_does_not_block_boot(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(startup_validator.shutil, "which", lambda name: None)
    with caplog.at_level(logging.WARNING):
        StartupValidator([tmp_path], None).validate()  # non-fatal - no raise
    assert any("fpcalc" in record.getMessage() for record in caplog.records)


def test_present_fpcalc_emits_no_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(startup_validator.shutil, "which", lambda name: "/usr/bin/fpcalc")
    with caplog.at_level(logging.WARNING):
        StartupValidator([tmp_path], None).validate()
    assert not any("fpcalc" in record.getMessage() for record in caplog.records)


def test_slskd_downloads_unset_warns_does_not_raise(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        StartupValidator([tmp_path], None, slskd_downloads_path=None).validate()
    assert any(
        "slskd_downloads_path is not set" in r.getMessage() for r in caplog.records
    )


def test_slskd_downloads_missing_warns_does_not_raise(tmp_path, caplog):
    missing = tmp_path / "no-such-downloads"
    with caplog.at_level(logging.WARNING):
        # Must NOT raise ConfigurationError - a bad mount boots DEGRADED.
        StartupValidator([tmp_path], None, slskd_downloads_path=missing).validate()
    assert any("slskd downloads" in r.getMessage() for r in caplog.records)


def test_slskd_downloads_healthy_same_fs_emits_no_warning(tmp_path, caplog):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    with caplog.at_level(logging.WARNING):
        StartupValidator([tmp_path], None, slskd_downloads_path=downloads).validate()
    assert not any("slskd" in r.getMessage().lower() for r in caplog.records)
