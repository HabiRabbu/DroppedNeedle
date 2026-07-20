"""Domain helpers for choosing among MusicBrainz recording releases."""

from __future__ import annotations


_VERSION_CHANGING_TYPES = {"live", "remix", "dj-mix", "mixtape/street", "demo"}


def recording_release_group_rank(
    *,
    release_status: str | None,
    secondary_types: tuple[str, ...] | list[str],
    primary_type: str | None,
    release_date: str | None,
    release_group_mbid: str,
) -> tuple[int, int, int, int, str, str]:
    """Return a stable same-recording rank where lower values are preferred."""
    official = 0 if (release_status or "").casefold() == "official" else 1
    version_changed = int(
        bool({item.casefold() for item in secondary_types} & _VERSION_CHANGING_TYPES)
    )
    primary = {"album": 0, "ep": 1, "single": 2}.get((primary_type or "").casefold(), 3)
    secondary_penalty = int(bool(secondary_types))
    return (
        official,
        version_changed,
        primary,
        secondary_penalty,
        release_date or "9999-99-99",
        release_group_mbid,
    )
