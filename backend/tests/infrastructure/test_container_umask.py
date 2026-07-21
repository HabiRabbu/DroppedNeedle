from __future__ import annotations

import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_entrypoint_defaults_to_secure_configurable_umask() -> None:
    entrypoint = REPOSITORY_ROOT / "entrypoint.sh"
    result = subprocess.run(
        ["sh", "-n", str(entrypoint)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    source = entrypoint.read_text()
    assert "REQUESTED_UMASK=${UMASK:-027}" in source
    assert 'umask "$REQUESTED_UMASK"' in source


@pytest.mark.parametrize("value", ["22x", "22", "888", "1027", "7777"])
def test_entrypoint_rejects_invalid_umask_before_startup(value: str) -> None:
    result = subprocess.run(
        ["sh", str(REPOSITORY_ROOT / "entrypoint.sh"), "true"],
        check=False,
        capture_output=True,
        text=True,
        env={"UMASK": value},
    )

    assert result.returncode == 1
    assert "must be three or four octal digits" in result.stdout


def test_unraid_template_uses_the_secure_default() -> None:
    root = ElementTree.parse(REPOSITORY_ROOT / "templates/droppedneedle.xml").getroot()
    setting = next(
        item for item in root.findall("Config") if item.get("Target") == "UMASK"
    )

    assert setting.get("Default") == "027"
    assert setting.text == "027"
