"""Domain models for Free Music, the native lawful download client (D24)."""

from infrastructure.msgspec_fastapi import AppStruct


class FreeMusicStatus:
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})


class FreeMusicTask(AppStruct):
    id: str
    user_id: str
    kind: str  # 'album' | 'track'
    mbid: str  # release group, or recording for a track
    artist: str
    title: str
    status: str
    created_at: float
    updated_at: float
    identifier: str = ""  # the archive.org item, once chosen
    licence_url: str = ""
    format: str = ""
    files_total: int = 0
    files_completed: int = 0
    bytes_total: int = 0
    bytes_downloaded: int = 0
    attempts: int = 0
    error: str | None = None


class FreeMusicCandidate(AppStruct):
    """One (archive item, format) pairing, ranked before download."""

    identifier: str
    title: str
    creator: str
    licence_url: str
    format: str
    extension: str
    track_count: int
    size_bytes: int
    filenames: list[str] = []
