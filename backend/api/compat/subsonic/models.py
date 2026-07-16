"""Subsonic response object structs + View DTO -> object formatters.

Field names are EXACT Subsonic/OpenSubsonic camelCase names so msgspec.to_builtins
emits the right keys. Optional list fields default None so the None-strip omits
them in list vs detail contexts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import msgspec

from api.compat.subsonic.ids import encode
from services.compat.view_models import ViewAlbum, ViewArtist, ViewGenre, ViewTrack

_MIME = {
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "wav": "audio/wav",
    "wma": "audio/x-ms-wma",
}


def mime_for(file_format: str) -> str:
    return _MIME.get((file_format or "").lower(), "application/octet-stream")


def iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def played_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except ValueError:
        return None


def genre_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _item_date(value: str | None) -> "SItemDate | None":
    if not value:
        return None
    parts = value.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else None
        day = int(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return None
    if not 1 <= year <= 9999 or month is not None and not 1 <= month <= 12:
        return None
    if day is not None and not 1 <= day <= 31:
        return None
    return SItemDate(year=year, month=month, day=day)


class SArtistID3(msgspec.Struct, kw_only=True):
    id: str
    name: str
    coverArt: str | None = None
    albumCount: int | None = None
    starred: str | None = None
    musicBrainzId: str | None = None
    sortName: str | None = None
    album: list["SAlbumID3"] | None = None  # populated by getArtist only


class SArtist(msgspec.Struct, kw_only=True):
    """File-structure artist (getIndexes / search2 / getStarred)."""

    id: str
    name: str
    starred: str | None = None
    coverArt: str | None = None


class SAlbumID3(msgspec.Struct, kw_only=True):
    id: str
    name: str
    artist: str | None = None
    artistId: str | None = None
    coverArt: str | None = None
    songCount: int | None = None
    duration: int | None = None
    playCount: int | None = None
    created: str | None = None
    starred: str | None = None
    year: int | None = None
    genre: str | None = None
    isCompilation: bool | None = None
    musicBrainzId: str | None = None
    played: str | None = None
    genres: list["SItemGenre"] | None = None
    artists: list[SArtistID3] | None = None
    displayArtist: str | None = None
    releaseTypes: list[str] | None = None
    sortName: str | None = None
    originalReleaseDate: "SItemDate | None" = None
    discTitles: list["SDiscTitle"] | None = None
    song: list["SChild"] | None = None  # populated by getAlbum only


class SChild(msgspec.Struct, kw_only=True):
    id: str
    isDir: bool = False
    title: str
    parent: str | None = None
    album: str | None = None
    artist: str | None = None
    track: int | None = None
    year: int | None = None
    genre: str | None = None
    coverArt: str | None = None
    size: int | None = None
    contentType: str | None = None
    suffix: str | None = None
    transcodedContentType: str | None = None
    transcodedSuffix: str | None = None
    duration: int | None = None
    bitRate: int | None = None
    path: str | None = None
    discNumber: int | None = None
    created: str | None = None
    starred: str | None = None
    albumId: str | None = None
    artistId: str | None = None
    type: str | None = None
    playCount: int | None = None
    # OpenSubsonic required-on-song fields
    mediaType: str | None = None
    bitDepth: int | None = None
    samplingRate: int | None = None
    channelCount: int | None = None
    musicBrainzId: str | None = None
    played: str | None = None
    sortName: str | None = None
    genres: list["SItemGenre"] | None = None
    artists: list[SArtistID3] | None = None
    displayArtist: str | None = None
    albumArtists: list[SArtistID3] | None = None
    displayAlbumArtist: str | None = None
    replayGain: "SReplayGain | None" = None


class SItemGenre(msgspec.Struct, kw_only=True):
    name: str


class SItemDate(msgspec.Struct, kw_only=True):
    year: int
    month: int | None = None
    day: int | None = None


class SDiscTitle(msgspec.Struct, kw_only=True):
    disc: int
    title: str
    coverArt: str | None = None


class SReplayGain(msgspec.Struct, kw_only=True):
    trackGain: float | None = None
    albumGain: float | None = None
    trackPeak: float | None = None
    albumPeak: float | None = None


class SNowPlayingEntry(SChild, kw_only=True):
    """getNowPlaying entry: a song Child plus session attribution."""

    username: str = ""
    minutesAgo: int = 0
    playerId: int = 0
    playerName: str | None = None


class SGenre(msgspec.Struct, kw_only=True):
    value: str
    songCount: int = 0
    albumCount: int = 0


class SPlaylist(msgspec.Struct, kw_only=True):
    id: str
    name: str
    comment: str | None = None
    owner: str | None = None
    public: bool | None = None
    songCount: int = 0
    duration: int | None = None
    created: str | None = None
    changed: str | None = None
    coverArt: str | None = None
    entry: list["SChild"] | None = None  # populated by getPlaylist only


class SIndexID3(msgspec.Struct, kw_only=True):
    name: str
    artist: list[SArtistID3] = []


class SArtistsID3(msgspec.Struct, kw_only=True):
    ignoredArticles: str = "The El La Los Las Le Les"
    index: list[SIndexID3] = []


class SIndex(msgspec.Struct, kw_only=True):
    name: str
    artist: list[SArtist] = []


class SIndexes(msgspec.Struct, kw_only=True):
    lastModified: int = 0
    ignoredArticles: str = "The El La Los Las Le Les"
    index: list[SIndex] = []


class SMusicFolder(msgspec.Struct, kw_only=True):
    id: int
    name: str


class SLicense(msgspec.Struct, kw_only=True):
    valid: bool = True


class SOpenSubsonicExtension(msgspec.Struct, kw_only=True):
    name: str
    versions: list[int]


class SPlayQueue(msgspec.Struct, kw_only=True):
    username: str
    changed: str
    changedBy: str
    current: str | None = None
    position: int | None = None
    entry: list["SChild"] = msgspec.field(default_factory=list)


class SPlayQueueByIndex(msgspec.Struct, kw_only=True):
    username: str
    changed: str
    changedBy: str
    currentIndex: int | None = None
    position: int | None = None
    entry: list["SChild"] = msgspec.field(default_factory=list)


class SBookmark(msgspec.Struct, kw_only=True):
    position: int
    username: str
    created: str
    changed: str
    entry: "SChild"
    comment: str | None = None


class SLyrics(msgspec.Struct, kw_only=True):
    artist: str
    title: str
    value: str


class SLyricsLine(msgspec.Struct, kw_only=True):
    value: str
    start: int | None = None


class SStructuredLyrics(msgspec.Struct, kw_only=True):
    lang: str
    synced: bool
    line: list[SLyricsLine]
    displayArtist: str | None = None
    displayTitle: str | None = None
    offset: float | None = None


class SArtistInfo(msgspec.Struct, kw_only=True):
    biography: str | None = None
    musicBrainzId: str | None = None
    lastFmUrl: str | None = None
    smallImageUrl: str | None = None
    mediumImageUrl: str | None = None
    largeImageUrl: str | None = None
    similarArtist: list[SArtist | SArtistID3] = msgspec.field(default_factory=list)


class SAlbumInfo(msgspec.Struct, kw_only=True):
    notes: str | None = None
    musicBrainzId: str | None = None
    lastFmUrl: str | None = None
    smallImageUrl: str | None = None
    mediumImageUrl: str | None = None
    largeImageUrl: str | None = None


class SScanStatus(msgspec.Struct, kw_only=True):
    scanning: bool
    count: int | None = None


class SDirectPlayProfile(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    containers: list[str]
    audioCodecs: list[str]
    protocols: list[str]
    maxAudioChannels: int | None = None


class STranscodingProfile(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    container: str
    audioCodec: str
    protocol: str
    maxAudioChannels: int | None = None


class SCodecLimitation(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    name: str
    comparison: str
    values: list[str]
    required: bool


class SCodecProfile(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    type: str
    name: str
    limitations: list[SCodecLimitation] = msgspec.field(default_factory=list)


class SClientInfo(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    name: str
    platform: str
    maxAudioBitrate: int | None = None
    maxTranscodingAudioBitrate: int | None = None
    directPlayProfiles: list[SDirectPlayProfile] = msgspec.field(default_factory=list)
    transcodingProfiles: list[STranscodingProfile] = msgspec.field(default_factory=list)
    codecProfiles: list[SCodecProfile] = msgspec.field(default_factory=list)


class SStreamDetails(msgspec.Struct, kw_only=True):
    protocol: str
    container: str
    codec: str
    audioChannels: int | None = None
    audioBitrate: int | None = None
    audioProfile: str | None = None
    audioSamplerate: int | None = None
    audioBitdepth: int | None = None


class STranscodeDecision(msgspec.Struct, kw_only=True):
    canDirectPlay: bool
    canTranscode: bool
    transcodeReason: list[str] = msgspec.field(default_factory=list)
    errorReason: str | None = None
    transcodeParams: str | None = None
    sourceStream: SStreamDetails | None = None
    transcodeStream: SStreamDetails | None = None


class SUser(msgspec.Struct, kw_only=True):
    username: str
    scrobblingEnabled: bool = True
    adminRole: bool = False
    settingsRole: bool = True
    downloadRole: bool = True
    uploadRole: bool = False
    playlistRole: bool = True
    coverArtRole: bool = True
    commentRole: bool = False
    podcastRole: bool = False
    streamRole: bool = True
    jukeboxRole: bool = False
    shareRole: bool = False
    videoConversionRole: bool = False
    maxBitRate: int | None = None
    folder: list[int] = msgspec.field(default_factory=lambda: [1])


def to_artist_id3(v: ViewArtist) -> SArtistID3:
    aid = encode("artist", v.artist_mbid)
    return SArtistID3(
        id=aid,
        name=v.name,
        coverArt=aid,
        albumCount=v.album_count,
        starred=iso(v.starred_at),
        musicBrainzId=v.musicbrainz_artist_id
        or (v.artist_mbid if not v.provider_identity_projected else None),
        sortName=v.name,
    )


def to_artist_file(v: ViewArtist) -> SArtist:
    aid = encode("artist", v.artist_mbid)
    return SArtist(id=aid, name=v.name, coverArt=aid, starred=iso(v.starred_at))


def to_album_id3(v: ViewAlbum) -> SAlbumID3:
    alid = encode("album", v.rg_mbid)
    return SAlbumID3(
        id=alid,
        name=v.title,
        artist=v.artist_name,
        artistId=encode("artist", v.artist_mbid) if v.artist_mbid else None,
        coverArt=alid,
        songCount=v.track_count,
        duration=round(v.total_duration_seconds)
        if v.total_duration_seconds is not None
        else None,
        playCount=v.play_count,
        created=iso(v.date_added),
        starred=iso(v.starred_at),
        year=v.year,
        genre=v.genre,
        isCompilation=v.is_compilation,
        musicBrainzId=v.musicbrainz_release_group_id
        or (v.rg_mbid if not v.provider_identity_projected else None),
        played=played_iso(v.played_at),
        genres=[SItemGenre(name=v.genre)] if v.genre else None,
        artists=[
            SArtistID3(
                id=encode("artist", v.artist_mbid),
                name=v.artist_name or "Unknown Artist",
                musicBrainzId=v.musicbrainz_artist_id
                or (v.artist_mbid if not v.provider_identity_projected else None),
            )
        ]
        if v.artist_mbid
        else None,
        displayArtist=v.artist_name,
        releaseTypes=["Compilation"] if v.is_compilation else None,
        sortName=v.sort_name or v.title,
        originalReleaseDate=_item_date(v.original_release_date),
        discTitles=[SDiscTitle(disc=disc, title=title) for disc, title in v.disc_titles]
        or None,
    )


def to_child(
    v: ViewTrack,
    *,
    transcoded_content_type: str | None = None,
    transcoded_suffix: str | None = None,
) -> SChild:
    alid = encode("album", v.rg_mbid) if v.rg_mbid else None
    track_artist = (
        SArtistID3(
            id=encode("artist", v.artist_mbid),
            name=v.artist_name,
            musicBrainzId=v.musicbrainz_artist_id
            or (v.artist_mbid if not v.provider_identity_projected else None),
        )
        if v.artist_mbid
        else None
    )
    album_artist = (
        SArtistID3(
            id=encode("artist", v.album_artist_mbid),
            name=v.album_artist_name or "Unknown Artist",
            musicBrainzId=v.musicbrainz_album_artist_id
            or (v.album_artist_mbid if not v.provider_identity_projected else None),
        )
        if v.album_artist_mbid
        else None
    )
    return SChild(
        id=encode("track", v.file_id),
        isDir=False,
        title=v.title,
        parent=alid,
        album=v.album_title,
        artist=v.artist_name,
        track=v.track_number or None,
        year=v.year,
        genre=v.genre,
        coverArt=alid,
        size=v.file_size_bytes or None,
        contentType=mime_for(v.file_format),
        suffix=v.file_format or None,
        transcodedContentType=transcoded_content_type,
        transcodedSuffix=transcoded_suffix,
        duration=round(v.duration_seconds),
        bitRate=v.bitrate,
        discNumber=v.disc_number or None,
        created=iso(v.created_at),
        starred=iso(v.starred_at),
        albumId=alid,
        artistId=encode("artist", v.artist_mbid) if v.artist_mbid else None,
        type="music",
        playCount=v.play_count,
        mediaType="song",
        bitDepth=v.bit_depth,
        samplingRate=v.sample_rate,
        channelCount=v.channels if v.channels is not None else 2,
        musicBrainzId=v.musicbrainz_recording_id
        or (v.recording_mbid if not v.provider_identity_projected else None),
        played=played_iso(v.played_at),
        sortName=v.sort_name or v.title,
        genres=[
            SItemGenre(name=name.strip())
            for name in (v.genre or "").split(";")
            if name.strip()
        ]
        or None,
        artists=[track_artist] if track_artist else None,
        displayArtist=v.artist_name or None,
        albumArtists=[album_artist] if album_artist else None,
        displayAlbumArtist=v.album_artist_name,
        replayGain=SReplayGain(
            trackGain=v.replaygain_track_gain,
            albumGain=v.replaygain_album_gain,
            trackPeak=v.replaygain_track_peak,
            albumPeak=v.replaygain_album_peak,
        ),
    )


def to_album_child(v: ViewAlbum) -> SChild:
    """Album as a file-structure Child (getAlbumList / getMusicDirectory dir)."""
    alid = encode("album", v.rg_mbid)
    return SChild(
        id=alid,
        isDir=True,
        title=v.title,
        album=v.title,
        artist=v.artist_name,
        artistId=encode("artist", v.artist_mbid) if v.artist_mbid else None,
        coverArt=alid,
        year=v.year,
        genre=v.genre,
        created=iso(v.date_added),
        starred=iso(v.starred_at),
        duration=round(v.total_duration_seconds)
        if v.total_duration_seconds is not None
        else None,
    )


def to_genre(v: ViewGenre) -> SGenre:
    return SGenre(value=v.name, songCount=v.song_count, albumCount=v.album_count)
