"""Tests for StartupValidator (basic Phase 3 checks + Phase 4 fpcalc check)."""

import logging
from types import SimpleNamespace

import pytest

from core import startup_validator
from core.exceptions import ConfigurationError
from core.startup_validator import StartupValidator


def test_missing_library_path_raises(tmp_path):
    with pytest.raises(ConfigurationError):
        StartupValidator([tmp_path / "does-not-exist"], None).validate()


def test_existing_library_path_ok(tmp_path):
    StartupValidator([tmp_path], None).validate()


def test_no_paths_warns_but_does_not_raise(tmp_path):
    StartupValidator([], None).validate()


def test_missing_staging_dir_is_auto_created(tmp_path):
    staging = tmp_path / "staging"
    assert not staging.exists()
    StartupValidator([tmp_path], staging).validate()
    assert staging.exists()


def test_staging_on_same_filesystem_ok(tmp_path):
    staging = tmp_path / "staging"
    StartupValidator([tmp_path], staging).validate()
    assert staging.exists()


def test_missing_path_reported_before_staging(tmp_path):
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
    monkeypatch.setattr(
        startup_validator.shutil, "which", lambda name: "/usr/bin/fpcalc"
    )
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
        StartupValidator([tmp_path], None, slskd_downloads_path=missing).validate()
    assert any("slskd downloads" in r.getMessage() for r in caplog.records)


def test_slskd_downloads_healthy_same_fs_emits_no_warning(tmp_path, caplog):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    with caplog.at_level(logging.WARNING):
        StartupValidator([tmp_path], None, slskd_downloads_path=downloads).validate()
    assert not any("slskd" in r.getMessage().lower() for r in caplog.records)


def test_slskd_separate_mount_warns_about_copy_fallback(tmp_path, monkeypatch, caplog):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(
        startup_validator,
        "check_move_boundary",
        lambda _source, _destination: SimpleNamespace(
            move_supported=False, reason="different_mount"
        ),
    )

    with caplog.at_level(logging.WARNING):
        StartupValidator([tmp_path], None, slskd_downloads_path=downloads).validate()

    assert any("copy and remove" in record.getMessage() for record in caplog.records)


def test_slskd_unknown_boundary_does_not_claim_a_separate_mount(
    tmp_path, monkeypatch, caplog
):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(
        startup_validator,
        "check_move_boundary",
        lambda _source, _destination: SimpleNamespace(
            move_supported=False, reason="stat_error"
        ),
    )

    with caplog.at_level(logging.WARNING):
        StartupValidator([tmp_path], None, slskd_downloads_path=downloads).validate()

    messages = [record.getMessage() for record in caplog.records]
    assert any("could not determine" in message for message in messages)
    assert not any("separate container mount" in message for message in messages)
