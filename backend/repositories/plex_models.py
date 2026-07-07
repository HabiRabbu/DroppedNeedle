from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import msgspec

from core.exceptions import PlexApiError

logger = logging.getLogger(__name__)


class PlexGuid(msgspec.Struct):
    id: str = ""


class PlexGenreTag(msgspec.Struct):
    tag: str = ""


class PlexPart(msgspec.Struct):
    id: int = 0
    key: str = ""
    duration: int = 0
    file: str = ""
    size: int = 0
    container: str = ""


class PlexMedia(msgspec.Struct):
    id: int = 0
    duration: int = 0
    bitrate: int = 0
    audioCodec: str = ""
    audioChannels: int = 0
    container: str = ""
    Part: list[PlexPart] = msgspec.field(default_factory=list)


class PlexArtist(msgspec.Struct):
    ratingKey: str = ""
    title: str = ""
    thumb: str = ""
    addedAt: int = 0
    Guid: list[PlexGuid] = msgspec.field(default_factory=list)


class PlexAlbum(msgspec.Struct):
    ratingKey: str = ""
    title: str = ""
    parentTitle: str = ""
    parentRatingKey: str = ""
    year: int = 0
    thumb: str = ""
    addedAt: int = 0
    lastViewedAt: int = 0
    viewCount: int = 0
    userRating: float = 0.0
    leafCount: int = 0
    Genre: list[PlexGenreTag] = msgspec.field(default_factory=list)
    Guid: list[PlexGuid] = msgspec.field(default_factory=list)


class PlexTrack(msgspec.Struct):
    ratingKey: str = ""
    title: str = ""
    parentTitle: str = ""
    grandparentTitle: str = ""
    parentRatingKey: str = ""
    index: int = 0
    parentIndex: int = 1
    duration: int = 0
    addedAt: int = 0
    Media: list[PlexMedia] = msgspec.field(default_factory=list)
    Guid: list[PlexGuid] = msgspec.field(default_factory=list)


class PlexPlaylist(msgspec.Struct):
    ratingKey: str = ""
    title: str = ""
    leafCount: int = 0
    duration: int = 0
    playlistType: str = ""
    smart: bool = False
    updatedAt: int = 0
    composite: str = ""


class PlexLibrarySection(msgspec.Struct):
    key: str = ""
    title: str = ""
    type: str = ""
    uuid: str = ""


class StreamProxyResult(msgspec.Struct):
    status_code: int
    headers: dict[str, str]
    media_type: str
    body_chunks: AsyncIterator[bytes] | None = None


class PlexOAuthPin(msgspec.Struct):
    id: int = 0
    code: str = ""
    authToken: str | None = None


class PlexAccount(msgspec.Struct):
    uuid: str = ""
    username: str = ""
    title: str = ""
    email: str | None = None
    thumb: str | None = None
    source: str = ""  # "home" | "friend"


class PlexUserProfile(msgspec.Struct):
    uuid: str = ""
    email: str | None = None
    display_name: str = "Plex User"
    thumb: str | None = None


def parse_plex_response(data: dict[str, Any]) -> dict[str, Any]:
    container = data.get("MediaContainer")
    if container is None:
        raise PlexApiError("Missing MediaContainer envelope in Plex response")
    return container


def parse_plex_account(entry: dict[str, Any], source: str) -> PlexAccount | None:
    # The account uuid is the join key (== account.uuid from get_token_details).
    # Skip any entry without it rather than risk a wrong provider_uid.
    uuid = (entry.get("uuid") or "").strip()
    if not uuid:
        return None
    username = entry.get("username") or ""
    title = entry.get("title") or entry.get("friendlyName") or username
    email = entry.get("email") or None
    thumb = entry.get("thumb") or None
    return PlexAccount(
        uuid=uuid,
        username=username,
        title=title,
        email=email,
        thumb=thumb,
        source=source,
    )


def parse_plex_user_profile(data: dict[str, Any]) -> PlexUserProfile:
    # /api/v2/user (token details). Lenient by design: we read only the identity
    # fields we need, so extra or missing fields in Plex's response never break
    # login. The generated plex-api-client model marked many fields required and
    # rejected real responses (e.g. accounts without all attributes).
    display = (
        data.get("friendlyName")
        or data.get("username")
        or data.get("title")
        or "Plex User"
    )
    return PlexUserProfile(
        uuid=(data.get("uuid") or "").strip(),
        email=data.get("email") or None,
        display_name=display,
        thumb=data.get("thumb") or None,
    )


def parse_plex_users(payload: Any, source: str) -> list[PlexAccount]:
    # /api/v2/home/users returns {"users": [...]}; /api/v2/friends returns a bare
    # list. Handle both.
    if isinstance(payload, dict):
        items = payload.get("users") or payload.get("friends") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    accounts: list[PlexAccount] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        account = parse_plex_account(item, source)
        if account is not None:
            accounts.append(account)
    return accounts


def parse_library_sections(container: dict[str, Any]) -> list[PlexLibrarySection]:
    raw = container.get("Directory", [])
    return [
        PlexLibrarySection(
            key=d.get("key", ""),
            title=d.get("title", ""),
            type=d.get("type", ""),
            uuid=d.get("uuid", ""),
        )
        for d in raw
    ]


def parse_artist(data: dict[str, Any]) -> PlexArtist:
    return PlexArtist(
        ratingKey=str(data.get("ratingKey", "")),
        title=data.get("title", "Unknown"),
        thumb=data.get("thumb", ""),
        addedAt=data.get("addedAt", 0),
        Guid=_parse_guids(data.get("Guid", [])),
    )


def parse_album(data: dict[str, Any]) -> PlexAlbum:
    return PlexAlbum(
        ratingKey=str(data.get("ratingKey", "")),
        title=data.get("title", "Unknown"),
        parentTitle=data.get("parentTitle", ""),
        parentRatingKey=str(data.get("parentRatingKey", "")),
        year=data.get("year", 0),
        thumb=data.get("thumb", ""),
        addedAt=data.get("addedAt", 0),
        lastViewedAt=data.get("lastViewedAt", 0),
        viewCount=data.get("viewCount", 0),
        userRating=float(data.get("userRating", 0.0)),
        leafCount=data.get("leafCount", 0),
        Genre=_parse_genre_tags(data.get("Genre", [])),
        Guid=_parse_guids(data.get("Guid", [])),
    )


def parse_track(data: dict[str, Any]) -> PlexTrack:
    media_list: list[PlexMedia] = []
    for m in data.get("Media", []):
        parts = [
            PlexPart(
                id=p.get("id", 0),
                key=p.get("key", ""),
                duration=p.get("duration", 0),
                file=p.get("file", ""),
                size=p.get("size", 0),
                container=p.get("container", ""),
            )
            for p in m.get("Part", [])
        ]
        media_list.append(
            PlexMedia(
                id=m.get("id", 0),
                duration=m.get("duration", 0),
                bitrate=m.get("bitrate", 0),
                audioCodec=m.get("audioCodec", ""),
                audioChannels=m.get("audioChannels", 0),
                container=m.get("container", ""),
                Part=parts,
            )
        )
    return PlexTrack(
        ratingKey=str(data.get("ratingKey", "")),
        title=data.get("title", "Unknown"),
        parentTitle=data.get("parentTitle", ""),
        grandparentTitle=data.get("grandparentTitle", ""),
        parentRatingKey=str(data.get("parentRatingKey", "")),
        index=data.get("index", 0),
        parentIndex=data.get("parentIndex", 1),
        duration=data.get("duration", 0),
        addedAt=data.get("addedAt", 0),
        Media=media_list,
        Guid=_parse_guids(data.get("Guid", [])),
    )


def parse_playlist(data: dict[str, Any]) -> PlexPlaylist:
    return PlexPlaylist(
        ratingKey=str(data.get("ratingKey", "")),
        title=data.get("title", ""),
        leafCount=data.get("leafCount", 0),
        duration=data.get("duration", 0),
        playlistType=data.get("playlistType", ""),
        smart=bool(data.get("smart", False)),
        updatedAt=data.get("updatedAt", 0),
        composite=data.get("composite", ""),
    )


def _parse_guids(raw: list[dict[str, Any]] | None) -> list[PlexGuid]:
    if not raw:
        return []
    return [PlexGuid(id=g.get("id", "")) for g in raw]


def _parse_genre_tags(raw: list[dict[str, Any]] | None) -> list[PlexGenreTag]:
    if not raw:
        return []
    return [PlexGenreTag(tag=g.get("tag", "")) for g in raw]


def extract_mbid_from_guids(guids: list[PlexGuid], prefix: str = "mbid://") -> str:
    for guid in guids:
        if guid.id.startswith(prefix):
            return guid.id[len(prefix):]
    return ""


class PlexSession(msgspec.Struct):
    session_id: str = ""
    user_name: str = ""
    track_title: str = ""
    artist_name: str = ""
    album_name: str = ""
    album_thumb: str = ""
    player_device: str = ""
    player_platform: str = ""
    player_state: str = ""
    is_direct_play: bool = True
    transcode_decision: str = ""
    progress_ms: int = 0
    duration_ms: int = 0
    audio_codec: str = ""
    audio_channels: int = 0
    bitrate: int = 0


class PlexHistoryEntry(msgspec.Struct):
    rating_key: str = ""
    track_title: str = ""
    artist_name: str = ""
    album_name: str = ""
    album_rating_key: str = ""
    viewed_at: int = 0
    duration_ms: int = 0
    device_name: str = ""
    player_platform: str = ""


def parse_plex_history(data: dict[str, Any]) -> tuple[list[PlexHistoryEntry], int]:
    """Extract audio-only history from Plex /status/sessions/history/all."""
    container = data.get("MediaContainer", data)
    total = container.get("totalSize", container.get("size", 0))
    entries: list[PlexHistoryEntry] = []
    for item in container.get("Metadata", []):
        if item.get("type") != "track":
            continue
        entries.append(PlexHistoryEntry(
            rating_key=str(item.get("ratingKey", "")),
            track_title=item.get("title", ""),
            artist_name=item.get("grandparentTitle", ""),
            album_name=item.get("parentTitle", ""),
            album_rating_key=str(item.get("parentRatingKey", "")),
            viewed_at=item.get("viewedAt", 0),
            duration_ms=item.get("duration", 0),
            device_name=item.get("Player", {}).get("title", "") if isinstance(item.get("Player"), dict) else "",
            player_platform=item.get("Player", {}).get("platform", "") if isinstance(item.get("Player"), dict) else "",
        ))
    return entries, total


def parse_plex_sessions(data: dict[str, Any]) -> list[PlexSession]:
    """Extract audio-only sessions from a Plex /status/sessions response."""
    container = data.get("MediaContainer", data)
    sessions: list[PlexSession] = []
    for track in container.get("Metadata", []):
        if track.get("type") != "track":
            continue
        user = track.get("User", {})
        player = track.get("Player", {})
        transcode = track.get("TranscodeSession", {})
        session = track.get("Session", {})
        player.get("local", False) or transcode.get("videoDecision") is None
        sessions.append(PlexSession(
            session_id=session.get("id", ""),
            user_name=user.get("title", ""),
            track_title=track.get("title", ""),
            artist_name=track.get("grandparentTitle", ""),
            album_name=track.get("parentTitle", ""),
            album_thumb=track.get("parentRatingKey", ""),
            player_device=player.get("title", ""),
            player_platform=player.get("platform", ""),
            player_state=player.get("state", "playing"),
            is_direct_play="directplay" in transcode.get("audioDecision", "directplay").lower(),
            transcode_decision=transcode.get("audioDecision", ""),
            progress_ms=track.get("viewOffset", 0),
            duration_ms=track.get("duration", 0),
            audio_codec=transcode.get("audioCodec", track.get("Media", [{}])[0].get("audioCodec", "") if track.get("Media") else ""),
            audio_channels=track.get("Media", [{}])[0].get("audioChannels", 0) if track.get("Media") else 0,
            bitrate=track.get("Media", [{}])[0].get("bitrate", 0) if track.get("Media") else 0,
        ))
    return sessions
