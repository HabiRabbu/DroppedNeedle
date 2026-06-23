import msgspec
from infrastructure.msgspec_fastapi import AppStruct


class ServiceConnection(AppStruct):
    name: str
    enabled: bool = False
    username: str = ""
    url: str = ""


class LibraryStats(AppStruct):
    source: str
    total_tracks: int = 0
    total_albums: int = 0
    total_artists: int = 0
    total_size_bytes: int = 0
    total_size_human: str = ""


class ProfileResponse(AppStruct):
    display_name: str = ""
    avatar_url: str = ""
    username: str | None = None
    username_display: str | None = None
    email: str | None = None
    providers: list[str] = msgspec.field(default_factory=list)
    services: list[ServiceConnection] = msgspec.field(default_factory=list)
    library_stats: list[LibraryStats] = msgspec.field(default_factory=list)


class ProfileUpdateRequest(AppStruct):
    display_name: str | None = None


class UsernameUpdateRequest(AppStruct):
    username: str


class EmailUpdateRequest(AppStruct):
    email: str | None = None


class ChangePasswordRequest(AppStruct):
    current_password: str
    new_password: str


class SetPasswordRequest(AppStruct):
    new_password: str
