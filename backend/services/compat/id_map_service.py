"""CompatIdMapService: stable 32-hex Jellyfin GUID <-> (kind, internal_id).

Deterministic derivation keeps ids stable even if a row is rebuilt; the persisted
table guarantees O(1) reverse lookup. Accepts dashed or undashed GUIDs on input,
always emits undashed.
"""

from __future__ import annotations

import hashlib

from core.exceptions import JellyfinError
from infrastructure.persistence.compat_id_map_store import CompatIdMapStore

VALID_KINDS = {"artist", "album", "track", "playlist", "genre", "library"}


def _normalize_jf_id(jf_id: str) -> str:
    return jf_id.replace("-", "").strip().lower()


class CompatIdMapService:
    def __init__(self, store: CompatIdMapStore) -> None:
        self._store = store

    async def to_jf(self, kind: str, internal_id: str) -> str:
        if kind not in VALID_KINDS:
            raise ValueError(f"Invalid compat id kind: {kind!r}")
        existing = await self._store.get_jf_id(kind, internal_id)
        if existing is not None:
            return existing
        jf_id = hashlib.sha256(f"{kind}:{internal_id}".encode("utf-8")).hexdigest()[:32]
        await self._store.insert(jf_id, kind, internal_id)
        return jf_id

    async def from_jf(self, jf_id: str) -> tuple[str, str]:
        mapping = await self._store.get_mapping(_normalize_jf_id(jf_id))
        if mapping is None:
            raise JellyfinError(404, f"Unknown item id: {jf_id}")
        return mapping
