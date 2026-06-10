"""Encryption helpers for sensitive data at rest (provider tokens, settings secrets)."""

from __future__ import annotations

import logging, os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv, set_key

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def init_crypto(config_dir: Path) -> None:
    global _fernet

    config_dir.mkdir(parents=True, exist_ok=True)
    env_file = config_dir / ".env"
    if not env_file.exists():
        env_file.touch()
        try:
            env_file.chmod(0o600)
        except OSError:
            pass

    load_dotenv(env_file)

    key = os.getenv("DATA_ENC_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        set_key(str(env_file), "DATA_ENC_KEY", key)
        os.environ["DATA_ENC_KEY"] = key
        logger.info(f"Generated new data encryption key at {env_file}")

    _fernet = Fernet(key.encode())


def _get_fernet() -> Fernet:
    if _fernet is None:
        raise RuntimeError("Crypto not initialized. Call init_crypto() during startup")
    return _fernet


def encrypt(value: str) -> str:
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> tuple[str, bool]:
    if not value:
        return value, False
    try:
        return _get_fernet().decrypt(value.encode()).decode(), False
    except InvalidToken:
        return value, True
