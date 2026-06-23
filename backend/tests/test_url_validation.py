"""Tests for validate_service_url in infrastructure.validators."""

import pytest

from core.exceptions import ValidationError
from infrastructure.validators import validate_service_url


def test_valid_http_url():
    result = validate_service_url("http://192.168.1.100:8096")
    assert result == "http://192.168.1.100:8096"


def test_valid_https_url():
    result = validate_service_url("https://jellyfin.local:8096")
    assert result == "https://jellyfin.local:8096"


def test_valid_localhost_url():
    result = validate_service_url("http://localhost:8096")
    assert result == "http://localhost:8096"


def test_blocks_file_scheme():
    with pytest.raises(ValidationError):
        validate_service_url("file:///etc/passwd")


def test_blocks_gopher_scheme():
    with pytest.raises(ValidationError):
        validate_service_url("gopher://evil.com")


def test_blocks_data_scheme():
    with pytest.raises(ValidationError):
        validate_service_url("data:text/html,<script>alert(1)</script>")


def test_blocks_ftp_scheme():
    with pytest.raises(ValidationError):
        validate_service_url("ftp://evil.com")


def test_blocks_empty_string():
    with pytest.raises(ValidationError):
        validate_service_url("")


def test_blocks_no_hostname():
    with pytest.raises(ValidationError):
        validate_service_url("http://")


def test_custom_label_in_error():
    with pytest.raises(ValidationError, match="Download Client URL"):
        validate_service_url("", label="Download Client URL")
