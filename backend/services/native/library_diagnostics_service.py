"""Bounded, redacted, ephemeral scan diagnostic export."""

from __future__ import annotations

import hashlib

import msgspec

from core.exceptions import ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore

MAX_DIAGNOSTIC_ROWS = 5_000
MAX_DIAGNOSTIC_BYTES = 2 * 1024 * 1024


class LibraryDiagnosticsService:
    def __init__(self, store: NativeLibraryStore) -> None:
        self._store = store

    async def export(self, run_id: str) -> tuple[str, bytes]:
        if (
            not run_id
            or len(run_id) > 128
            or any(character in run_id for character in "/\\\r\n")
        ):
            raise ValidationError("The scan run ID is invalid.")
        snapshot = await self._store.diagnostic_snapshot(
            run_id, row_limit=MAX_DIAGNOSTIC_ROWS
        )
        run = snapshot["run"]
        safe_run = {
            key: value
            for key, value in run.items()
            if key
            not in {
                "requested_by_user_id",
                "lease_owner",
            }
        }
        safe_scopes = []
        for scope in snapshot["scopes"]:
            safe_scopes.append(
                {
                    **{
                        key: value
                        for key, value in scope.items()
                        if key != "relative_path"
                    },
                    "relative_path_hash": self._hash_path(str(scope["relative_path"])),
                }
            )
        safe_inventory = [
            {
                **{key: value for key, value in item.items() if key != "relative_path"},
                "relative_path_hash": self._hash_path(str(item["relative_path"])),
            }
            for item in snapshot["inventory"]
        ]
        document = {
            "format": "droppedneedle-library-diagnostic-v1",
            "run": safe_run,
            "scopes": safe_scopes,
            "scopes_truncated": snapshot["scopes_truncated"],
            "inventory": safe_inventory,
            "inventory_truncated": snapshot["inventory_truncated"],
            "exported_row_count": snapshot["exported_row_count"],
            "evidence_storage": snapshot["evidence"],
            "limits": {
                "maximum_rows": MAX_DIAGNOSTIC_ROWS,
                "maximum_bytes": MAX_DIAGNOSTIC_BYTES,
            },
            "excluded": [
                "credentials",
                "full_filesystem_paths",
                "raw_provider_responses",
                "exception_text",
            ],
        }
        encoded = msgspec.json.encode(document, order="deterministic")
        if len(encoded) > MAX_DIAGNOSTIC_BYTES:
            raise ValidationError(
                "The diagnostic report exceeds the safe export limit."
            )
        opaque_id = hashlib.sha256(run_id.encode()).hexdigest()[:16]
        return f"droppedneedle-library-run-{opaque_id}.json", encoded

    @staticmethod
    def _hash_path(path: str) -> str:
        return hashlib.sha256(path.encode()).hexdigest()
