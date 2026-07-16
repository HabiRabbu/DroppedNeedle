"""Process-wide logging setup shared by the source and target entrypoints."""

from __future__ import annotations

import logging


class ExtraFieldFormatter(logging.Formatter):
    _RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
        "message",
        "asctime",
        "taskName",
        "color_message",
    }

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = " ".join(
            f"{key}={value}"
            for key, value in record.__dict__.items()
            if key not in self._RESERVED and not key.startswith("_")
        )
        return f"{base} | {extras}" if extras else base


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        ExtraFieldFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)

    from api.compat.common.redact import install_uvicorn_access_credential_filter

    install_uvicorn_access_credential_filter()
