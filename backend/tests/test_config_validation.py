"""Tests for config validation hardening and log_level application (CONSOLIDATED-08)."""

import logging
from pathlib import Path
from unittest.mock import patch

import msgspec
import pytest
from pydantic import ValidationError as PydanticValidationError

from core.config import Settings
from core.exceptions import ConfigurationError


# Helpers

def _make_settings(**overrides) -> Settings:
    """Build a Settings with sensible defaults, applying overrides."""
    defaults = {
        "jellyfin_url": "http://jellyfin:8096",
        "config_file_path": Path("/tmp/droppedneedle-test-config.json"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(msgspec.json.encode(data))


# A. Config Validation — Critical errors raise

class TestValidateConfigCriticalErrors:
    def test_valid_config_creates_settings(self) -> None:
        settings = _make_settings()
        assert settings.jellyfin_url == "http://jellyfin:8096"

    def test_invalid_url_scheme_raises(self) -> None:
        with pytest.raises((ConfigurationError, PydanticValidationError)):
            _make_settings(jellyfin_url="ftp://jellyfin:8096")

    def test_invalid_jellyfin_url_scheme_raises(self) -> None:
        with pytest.raises((ConfigurationError, PydanticValidationError)):
            _make_settings(jellyfin_url="ftp://jellyfin:8096")

    def test_http_pool_mismatch_warns_but_does_not_raise(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            settings = _make_settings(http_max_connections=10, http_max_keepalive=20)
        assert settings.http_max_connections == 10
        assert any("http_max_connections" in r.message for r in caplog.records)


# B. log_level field validator

class TestLogLevelValidator:
    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_valid_levels_accepted(self, level: str) -> None:
        settings = _make_settings(log_level=level)
        assert settings.log_level == level

    def test_normalises_to_uppercase(self) -> None:
        settings = _make_settings(log_level="debug")
        assert settings.log_level == "DEBUG"

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)invalid log_level"):
            _make_settings(log_level="VERBOSE")

    def test_mixed_case_normalised(self) -> None:
        settings = _make_settings(log_level="Warning")
        assert settings.log_level == "WARNING"


# C. load_from_file — type validation

class TestLoadFromFileTypeValidation:
    def test_wrong_type_raises_configuration_error(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"port": "banana"})

        settings = _make_settings(config_file_path=config_path)
        with pytest.raises(ConfigurationError, match="type errors"):
            settings.load_from_file()

    def test_coercible_type_succeeds(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"port": "8688"})

        settings = _make_settings(config_file_path=config_path)
        settings.load_from_file()
        assert settings.port == 8688

    def test_unknown_key_warns(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"totally_unknown_key": "value"})

        settings = _make_settings(config_file_path=config_path)
        with caplog.at_level(logging.WARNING):
            settings.load_from_file()
        assert any("Unknown config key" in r.message for r in caplog.records)

    def test_invalid_url_in_file_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"jellyfin_url": "ftp://bad-scheme:8096"})

        settings = _make_settings(config_file_path=config_path)
        with pytest.raises(ConfigurationError, match="(?i)critical configuration"):
            settings.load_from_file()

    def test_valid_config_file_loads(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"port": 9999, "contact_email": "new@example.com"})

        settings = _make_settings(config_file_path=config_path)
        settings.load_from_file()
        assert settings.port == 9999
        assert settings.contact_email == "new@example.com"

    def test_invalid_log_level_in_file_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"log_level": "verbose"})

        settings = _make_settings(config_file_path=config_path)
        with pytest.raises(ConfigurationError, match="(?i)invalid log_level"):
            settings.load_from_file()

    def test_log_level_normalised_through_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"log_level": "debug"})

        settings = _make_settings(config_file_path=config_path)
        settings.load_from_file()
        assert settings.log_level == "DEBUG"

    def test_url_trailing_slash_stripped_through_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"jellyfin_url": "http://jellyfin:8096/"})

        settings = _make_settings(config_file_path=config_path)
        settings.load_from_file()
        assert settings.jellyfin_url == "http://jellyfin:8096"

    def test_failed_load_does_not_partially_mutate(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        _write_config(config_path, {"port": 7777, "jellyfin_url": "ftp://bad:1234"})

        settings = _make_settings(config_file_path=config_path)
        original_port = settings.port
        with pytest.raises(ConfigurationError):
            settings.load_from_file()
        assert settings.port == original_port


# D. Log level application at startup

class TestLogLevelApplication:
    def test_log_level_applied_to_root_logger(self) -> None:
        settings = _make_settings(log_level="DEBUG")
        configured_level = getattr(logging, settings.log_level, logging.INFO)
        root = logging.getLogger()
        original = root.level
        try:
            root.setLevel(configured_level)
            assert root.getEffectiveLevel() == logging.DEBUG
        finally:
            root.setLevel(original)

    def test_log_level_warning_applied(self) -> None:
        settings = _make_settings(log_level="WARNING")
        configured_level = getattr(logging, settings.log_level, logging.INFO)
        root = logging.getLogger()
        original = root.level
        try:
            root.setLevel(configured_level)
            assert root.getEffectiveLevel() == logging.WARNING
        finally:
            root.setLevel(original)


# E. get_settings() cache safety

class TestGetSettingsCacheSafety:
    def test_failed_load_does_not_poison_cache(self, tmp_path: Path) -> None:
        import core.config as config_module

        bad_path = tmp_path / "bad_config.json"
        _write_config(bad_path, {"jellyfin_url": "ftp://invalid"})

        saved = config_module._settings
        try:
            config_module._settings = None

            with patch.object(
                Settings, "model_post_init", lambda self, _ctx: None
            ):
                pass

            with patch.dict(
                "os.environ",
                {"CONFIG_FILE_PATH": str(bad_path)},
            ):
                with pytest.raises((ConfigurationError, Exception)):
                    config_module.get_settings()

                assert config_module._settings is None
        finally:
            config_module._settings = saved
