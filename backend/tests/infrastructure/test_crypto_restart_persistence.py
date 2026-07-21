from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from cryptography.fernet import Fernet


BACKEND_ROOT = Path(__file__).resolve().parents[2]


_RESTART_SCRIPT = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    from api.v1.schemas.settings import DownloadClientConnectionSettings
    from core.config import Settings
    from infrastructure.crypto import init_crypto
    from repositories.slskd.slskd_repository import SlskdRepository
    from services.preferences_service import PreferencesService

    root = Path(sys.argv[2])
    init_crypto(root / "config")
    preferences = PreferencesService(Settings(root_app_dir=root))
    if sys.argv[1] == "save":
        preferences.save_download_client_settings(
            DownloadClientConnectionSettings(
                enabled=True,
                url="http://slskd:5030",
                api_key="restart-secret",
            )
        )
    else:
        settings = preferences.get_download_client_settings_raw()
        repository = SlskdRepository(
            None, settings.url, settings.api_key, root / "downloads"
        )
        assert settings.api_key == "restart-secret"
        assert repository.is_configured()
    """
)


def _isolated_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("DATA_ENC_KEY", None)
    environment["PYTHONPATH"] = str(BACKEND_ROOT)
    return environment


def test_generated_key_survives_a_real_process_restart(tmp_path: Path) -> None:
    environment = _isolated_environment()

    for mode in ("save", "load"):
        result = subprocess.run(
            [sys.executable, "-c", _RESTART_SCRIPT, mode, str(tmp_path)],
            cwd=BACKEND_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    assert (tmp_path / "config/.env").read_text().startswith("DATA_ENC_KEY=")


def test_explicit_environment_key_takes_precedence_over_config_file(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    file_key = Fernet.generate_key().decode()
    environment_key = Fernet.generate_key().decode()
    config_dir.joinpath(".env").write_text(f"DATA_ENC_KEY={file_key}\n")
    ciphertext = Fernet(environment_key.encode()).encrypt(b"expected").decode()
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        from infrastructure.crypto import decrypt, init_crypto

        init_crypto(Path(sys.argv[1]))
        plaintext, invalid = decrypt(sys.argv[2])
        assert not invalid
        assert plaintext == "expected"
        """
    )
    environment = _isolated_environment()
    environment["DATA_ENC_KEY"] = environment_key

    result = subprocess.run(
        [sys.executable, "-c", script, str(config_dir), ciphertext],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
