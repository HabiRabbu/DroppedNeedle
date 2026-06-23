import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ROOT_APP_DIR", tempfile.mkdtemp())

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.crypto import init_crypto

init_crypto(Path(os.environ["ROOT_APP_DIR"]) / "config")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end test that may require external services (e.g. a real slskd container)",
    )
