"""Safe self-avatar file resolution for compatibility clients."""

from __future__ import annotations

from pathlib import Path


class CompatAvatarService:
    _TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }

    def __init__(self, cache_dir: Path) -> None:
        self._avatar_dir = cache_dir / "avatars"

    def resolve(self, user_id: str) -> tuple[Path, str] | None:
        if not user_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in user_id):
            return None
        for suffix, media_type in self._TYPES.items():
            path = self._avatar_dir / f"{user_id}{suffix}"
            if path.is_file():
                return path, media_type
        return None
