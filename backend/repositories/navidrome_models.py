from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import msgspec

from core.exceptions import NavidromeApiError, NavidromeAuthError, NavidromeSubsonicError


class SubsonicArtist(msgspec.Struct):
    id: str
    name: str
    albumCount: int = 0
    coverArt: str = ""
    musicBrainzId: str = ""


class SubsonicSong(msgspec.Struct):
    id: str
    title: str
    album: str = ""
    albumId: str = ""
    artist: str = ""
    artistId: str = ""
    track: int = 0
    discNumber: int = 1
    year: int = 0
    duration: int = 0
    bitRate: int = 0
    suffix: str = ""
    contentType: str = ""
    coverArt: str = ""
    musicBrainzId: str = ""


class SubsonicAlbum(msgspec.Struct):
    id: str
    name: str
    artist: str = ""
    artistId: str = ""
    year: int = 0
    genre: str = ""
    songCount: int = 0
    duration: int = 0
    coverArt: str = ""
    musicBrainzId: str = ""
    song: list[SubsonicSong] | None = None


class SubsonicPlaylist(msgspec.Struct):
    id: str
    name: str
    songCount: int = 0
    duration: int = 0
    owner: str = ""
    public: bool = False
    created: str = ""
    changed: str = ""
    coverArt: str = ""
    entry: list[SubsonicSong] | None = None


class SubsonicGenre(msgspec.Struct):
    name: str = ""
    songCount: int = 0
    albumCount: int = 0


class SubsonicArtistIndex(msgspec.Struct):
    name: str = ""
    artists: list[SubsonicArtist] = msgspec.field(default_factory=list)


class SubsonicMusicFolder(msgspec.Struct):
    id: str = ""
    name: str = ""


class SubsonicSearchResult(msgspec.Struct):
    artist: list[SubsonicArtist] = msgspec.field(default_factory=list)
    album: list[SubsonicAlbum] = msgspec.field(default_factory=list)
    song: list[SubsonicSong] = msgspec.field(default_factory=list)


class StreamProxyResult(msgspec.Struct):
    status_code: int
    headers: dict[str, str]
    media_type: str
    body_chunks: AsyncIterator[bytes] | None = None


def parse_subsonic_response(data: dict[str, Any]) -> dict[str, Any]:
    resp = data.get("subsonic-response")
    if resp is None:
        raise NavidromeApiError("Missing subsonic-response envelope")
    status = resp.get("status", "")
    if status != "ok":
        error = resp.get("error", {})
        code = error.get("code", 0)
        message = error.get("message", "Unknown Subsonic API error")
        if code in (40, 41):
            raise NavidromeAuthError(message, code=code)
        raise NavidromeSubsonicError(message, code=code)
    return resp


def parse_artist(data: dict[str, Any]) -> SubsonicArtist:
    return SubsonicArtist(
        id=data.get("id", ""),
        name=data.get("name", "Unknown"),
        albumCount=data.get("albumCount", 0),
        coverArt=data.get("coverArt", ""),
        musicBrainzId=data.get("musicBrainzId", ""),
    )


def parse_song(data: dict[str, Any]) -> SubsonicSong:
    return SubsonicSong(
        id=data.get("id", ""),
        title=data.get("title", "Unknown"),
        album=data.get("album", ""),
        albumId=data.get("albumId", ""),
        artist=data.get("artist", ""),
        artistId=data.get("artistId", ""),
        track=data.get("track", 0),
        discNumber=data.get("discNumber", 1),
        year=data.get("year", 0),
        duration=data.get("duration", 0),
        bitRate=data.get("bitRate", 0),
        suffix=data.get("suffix", ""),
        contentType=data.get("contentType", ""),
        coverArt=data.get("coverArt", ""),
        musicBrainzId=data.get("musicBrainzId", ""),
    )


def parse_album(data: dict[str, Any]) -> SubsonicAlbum:
    songs: list[SubsonicSong] | None = None
    raw_songs = data.get("song")
    if raw_songs is not None:
        songs = [parse_song(s) for s in raw_songs]

    return SubsonicAlbum(
        id=data.get("id", ""),
        name=data.get("name", data.get("title", "Unknown")),
        artist=data.get("artist", ""),
        artistId=data.get("artistId", ""),
        year=data.get("year", 0),
        genre=data.get("genre", ""),
        songCount=data.get("songCount", 0),
        duration=data.get("duration", 0),
        coverArt=data.get("coverArt", ""),
        musicBrainzId=data.get("musicBrainzId", ""),
        song=songs,
    )


def parse_genre(data: dict[str, Any]) -> SubsonicGenre:
    return SubsonicGenre(
        name=data.get("value", data.get("name", "")),
        songCount=data.get("songCount", 0),
        albumCount=data.get("albumCount", 0),
    )


class SubsonicArtistInfo(msgspec.Struct):
    biography: str = ""
    musicBrainzId: str = ""
    smallImageUrl: str = ""
    mediumImageUrl: str = ""
    largeImageUrl: str = ""
    similarArtist: list[SubsonicArtist] = msgspec.field(default_factory=list)


class SubsonicNowPlayingEntry(msgspec.Struct):
    id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    albumId: str = ""
    artistId: str = ""
    coverArt: str = ""
    duration: int = 0
    bitRate: int = 0
    suffix: str = ""
    username: str = ""
    minutesAgo: int = 0
    playerId: int = 0
    playerName: str = ""


def parse_now_playing_entries(data: dict[str, Any]) -> list[SubsonicNowPlayingEntry]:
    """Extract now-playing entries from a Subsonic getNowPlaying response."""
    np = data.get("nowPlaying", {})
    entries_raw = np.get("entry", [])
    if not entries_raw:
        return []
    result: list[SubsonicNowPlayingEntry] = []
    for e in entries_raw:
        result.append(SubsonicNowPlayingEntry(
            id=e.get("id", ""),
            title=e.get("title", ""),
            artist=e.get("artist", ""),
            album=e.get("album", ""),
            albumId=e.get("albumId", ""),
            artistId=e.get("artistId", ""),
            coverArt=e.get("coverArt", ""),
            duration=e.get("duration", 0),
            bitRate=e.get("bitRate", 0),
            suffix=e.get("suffix", ""),
            username=e.get("username", ""),
            minutesAgo=e.get("minutesAgo", 0),
            playerId=e.get("playerId", 0),
            playerName=e.get("playerName", ""),
        ))
    return result


def parse_artist_info(data: dict[str, Any]) -> SubsonicArtistInfo:
    """Extract artist info from a Subsonic getArtistInfo2 response."""
    info = data.get("artistInfo2", {})
    if not info:
        return SubsonicArtistInfo()
    similar_raw = info.get("similarArtist", [])
    similar = [parse_artist(a) for a in similar_raw] if similar_raw else []
    return SubsonicArtistInfo(
        biography=info.get("biography", ""),
        musicBrainzId=info.get("musicBrainzId", ""),
        smallImageUrl=info.get("smallImageUrl", ""),
        mediumImageUrl=info.get("mediumImageUrl", ""),
        largeImageUrl=info.get("largeImageUrl", ""),
        similarArtist=similar,
    )


class SubsonicAlbumInfo(msgspec.Struct):
    notes: str = ""
    musicBrainzId: str = ""
    lastFmUrl: str = ""
    smallImageUrl: str = ""
    mediumImageUrl: str = ""
    largeImageUrl: str = ""


class SubsonicLyricLine(msgspec.Struct):
    value: str = ""
    start: int | None = None  # milliseconds from OpenSubsonic structuredLyrics


class SubsonicLyrics(msgspec.Struct):
    value: str = ""
    artist: str = ""
    title: str = ""
    lines: list[SubsonicLyricLine] = []
    is_synced: bool = False


def parse_album_info(data: dict[str, Any]) -> SubsonicAlbumInfo:
    """Extract album info from a Subsonic getAlbumInfo2 response."""
    info = data.get("albumInfo", {})
    if not info:
        return SubsonicAlbumInfo()
    return SubsonicAlbumInfo(
        notes=info.get("notes", ""),
        musicBrainzId=info.get("musicBrainzId", ""),
        lastFmUrl=info.get("lastFmUrl", ""),
        smallImageUrl=info.get("smallImageUrl", ""),
        mediumImageUrl=info.get("mediumImageUrl", ""),
        largeImageUrl=info.get("largeImageUrl", ""),
    )


def parse_lyrics(data: dict[str, Any]) -> SubsonicLyrics | None:
    """Extract lyrics from a Subsonic getLyrics response."""
    lyrics = data.get("lyrics", {})
    if not lyrics:
        return None
    value = lyrics.get("value", "")
    if not value:
        return None
    return SubsonicLyrics(
        value=value,
        artist=lyrics.get("artist", ""),
        title=lyrics.get("title", ""),
    )


def parse_top_songs(data: dict[str, Any]) -> list[SubsonicSong]:
    """Extract songs from a Subsonic getTopSongs response."""
    raw = data.get("topSongs", {}).get("song", [])
    return [parse_song(s) for s in raw] if raw else []


def parse_similar_songs(data: dict[str, Any]) -> list[SubsonicSong]:
    """Extract songs from a Subsonic getSimilarSongs2 response."""
    raw = data.get("similarSongs2", {}).get("song", [])
    return [parse_song(s) for s in raw] if raw else []
