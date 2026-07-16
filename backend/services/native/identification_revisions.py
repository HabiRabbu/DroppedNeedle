"""Stable revision inputs shared by identification and coverage."""

from __future__ import annotations

import hashlib


def _digest(values: list[str]) -> str:
    return hashlib.sha256("|".join(values).encode()).hexdigest()


def album_input_revisions(tracks: list[dict]) -> tuple[str, str, str]:
    ordered = sorted(tracks, key=lambda track: str(track["id"]))
    return (
        _digest([f"{track['id']}:{track['tag_revision'] or ''}" for track in ordered]),
        _digest([f"{track['id']}:{track['stat_revision']}" for track in ordered]),
        _digest(
            [
                f"{track['id']}:{track['applied_policy_revision']}:{track['applied_policy']}"
                for track in ordered
            ]
        ),
    )
