"""Type-prefixed Subsonic ids (01-architecture.md s6.1).

Prefix by type so one getCoverArt/star/id route resolves to the right kind.
Internal ids: artist=artist_mbid, album=rg_mbid, track=file_id,
playlist=playlist_id, genre=slug.
"""

from __future__ import annotations

from core.exceptions import SubsonicError

_PREFIX = {
    "artist": "ar-",
    "album": "al-",
    "track": "tr-",
    "playlist": "pl-",
    "genre": "ge-",
}
_BY_PREFIX = {v: k for k, v in _PREFIX.items()}


def encode(kind: str, internal_id: str) -> str:
    try:
        return _PREFIX[kind] + internal_id
    except KeyError as exc:
        raise ValueError(f"Unknown id kind: {kind!r}") from exc


def decode(sid: str) -> tuple[str, str]:
    """(kind, internal_id) for a prefixed id; unknown prefix -> Subsonic error 70."""
    for prefix, kind in _BY_PREFIX.items():
        if sid.startswith(prefix):
            return kind, sid[len(prefix):]
    raise SubsonicError(70, f"Invalid id: {sid}")
