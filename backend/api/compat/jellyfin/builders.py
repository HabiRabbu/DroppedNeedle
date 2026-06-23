"""View DTO -> Jellyfin BaseItemDto builder (06-data-mapping.md s5)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from api.compat.jellyfin.models import (
    BaseItemDto,
    NameGuidPair,
    UserItemDataDto,
)
from infrastructure.constants import JELLYFIN_TICKS_PER_SECOND

if TYPE_CHECKING:
    from repositories.coverart_repository import CoverArtRepository
    from services.compat.id_map_service import CompatIdMapService
    from services.compat.view_models import (
        ViewAlbum,
        ViewArtist,
        ViewGenre,
        ViewPlaylist,
        ViewTrack,
    )

LIBRARY_INTERNAL_ID = "music"


def ticks(seconds: float | None) -> int | None:
    if seconds is None:
        return None
    return round(seconds * JELLYFIN_TICKS_PER_SECOND)


def genre_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


# Manet requires DateCreated present, so never emit null even with no library date.
_DEFAULT_DATE = "1970-01-01T00:00:00.0000000Z"


def _iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone

    # .NET "O" round-trip format: strict clients (Manet) reject whole-second ISO,
    # the 7-digit fraction is required.
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond:06d}0Z"


class JellyfinBuilder:
    def __init__(
        self,
        id_map: "CompatIdMapService",
        coverart: "CoverArtRepository",
        server_id: str,
    ) -> None:
        self._ids = id_map
        self._cover = coverart
        self._sid = server_id
        self._album_tag_cache: dict[str, str | None] = {}

    async def _album_tag(self, rg_mbid: str | None) -> str | None:
        if not rg_mbid:
            return None
        if rg_mbid not in self._album_tag_cache:
            try:
                self._album_tag_cache[rg_mbid] = (
                    await self._cover.get_release_group_cover_etag(rg_mbid)
                )
            except Exception:  # noqa: BLE001 - art is best-effort
                self._album_tag_cache[rg_mbid] = None
        return self._album_tag_cache[rg_mbid]

    async def _artist_tag(self, artist_mbid: str | None) -> str | None:
        if not artist_mbid:
            return None
        try:
            return await self._cover.get_artist_image_etag(artist_mbid)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _user_data(item_id: str, *, starred_at, play_count) -> UserItemDataDto:
        count = play_count or 0
        return UserItemDataDto(
            ItemId=item_id, Key=item_id,
            PlayCount=count, Played=count > 0,
            IsFavorite=starred_at is not None,
        )

    async def audio(self, t: "ViewTrack") -> BaseItemDto:
        track_id = await self._ids.to_jf("track", t.file_id)
        album_id = await self._ids.to_jf("album", t.rg_mbid) if t.rg_mbid else None
        artist_mbid = t.artist_mbid
        album_artist_mbid = t.album_artist_mbid or t.artist_mbid
        artist_jf = await self._ids.to_jf("artist", artist_mbid) if artist_mbid else None
        album_artist_jf = (
            await self._ids.to_jf("artist", album_artist_mbid)
            if album_artist_mbid else None
        )
        album_tag = await self._album_tag(t.rg_mbid)
        provider_ids = {"MusicBrainzTrack": t.recording_mbid} if t.recording_mbid else None
        return BaseItemDto(
            Id=track_id, Name=t.title, ServerId=self._sid, Type="Audio",
            IsFolder=False, MediaType="Audio", SortName=t.title,
            RunTimeTicks=ticks(t.duration_seconds),
            ProductionYear=t.year,
            IndexNumber=t.track_number or None,
            ParentIndexNumber=t.disc_number or None,
            Album=t.album_title, AlbumId=album_id,
            AlbumArtist=t.album_artist_name or t.artist_name,
            # Jellyfin emits these as a (possibly empty) array, never null; strict
            # clients (Manet) require them present.
            AlbumArtists=[NameGuidPair(Name=t.album_artist_name or t.artist_name,
                                       Id=album_artist_jf)] if album_artist_jf else [],
            ArtistItems=[NameGuidPair(Name=t.artist_name, Id=artist_jf)] if artist_jf else [],
            Artists=[t.artist_name] if t.artist_name else [],
            AlbumPrimaryImageTag=album_tag,
            ImageTags={"Primary": album_tag} if album_tag else {},
            ParentId=album_id, Container=t.file_format or None,
            Genres=[t.genre] if t.genre else [],
            ProviderIds=provider_ids,
            DateCreated=_iso(t.created_at) or _DEFAULT_DATE,
            UserData=self._user_data(track_id, starred_at=t.starred_at,
                                     play_count=t.play_count),
        )

    async def album(self, a: "ViewAlbum") -> BaseItemDto:
        album_id = await self._ids.to_jf("album", a.rg_mbid)
        artist_jf = await self._ids.to_jf("artist", a.artist_mbid) if a.artist_mbid else None
        tag = await self._album_tag(a.rg_mbid)
        return BaseItemDto(
            Id=album_id, Name=a.title, ServerId=self._sid, Type="MusicAlbum",
            IsFolder=True, MediaType="Unknown", SortName=a.title,
            RunTimeTicks=ticks(a.total_duration_seconds),
            ProductionYear=a.year, ChildCount=a.track_count,
            AlbumArtist=a.artist_name,
            AlbumArtists=[NameGuidPair(Name=a.artist_name, Id=artist_jf)]
            if (artist_jf and a.artist_name) else [],
            ArtistItems=[NameGuidPair(Name=a.artist_name, Id=artist_jf)]
            if (artist_jf and a.artist_name) else [],
            Artists=[a.artist_name] if a.artist_name else [],
            Genres=[a.genre] if a.genre else [],
            ImageTags={"Primary": tag} if tag else {},
            ProviderIds={"MusicBrainzReleaseGroup": a.rg_mbid},
            DateCreated=_iso(a.date_added) or _DEFAULT_DATE,
            UserData=self._user_data(album_id, starred_at=a.starred_at,
                                     play_count=a.play_count),
        )

    async def artist(self, ar: "ViewArtist") -> BaseItemDto:
        artist_id = await self._ids.to_jf("artist", ar.artist_mbid)
        tag = await self._artist_tag(ar.artist_mbid)
        return BaseItemDto(
            Id=artist_id, Name=ar.name, ServerId=self._sid, Type="MusicArtist",
            IsFolder=True, MediaType="Unknown", ChildCount=ar.album_count,
            ImageTags={"Primary": tag} if tag else {},
            ProviderIds={"MusicBrainzArtist": ar.artist_mbid},
            SortName=ar.name, Genres=[],
            DateCreated=_iso(ar.date_added) or _DEFAULT_DATE,
            UserData=self._user_data(artist_id, starred_at=ar.starred_at,
                                     play_count=None),
        )

    async def playlist(self, p: "ViewPlaylist") -> BaseItemDto:
        pid = await self._ids.to_jf("playlist", p.id)
        return BaseItemDto(
            Id=pid, Name=p.name, ServerId=self._sid, Type="Playlist",
            IsFolder=True, MediaType="Audio", ChildCount=p.track_count,
            SortName=p.name,
            RunTimeTicks=ticks(p.total_duration_seconds),
            UserData=self._user_data(pid, starred_at=None, play_count=None),
        )

    async def genre(self, g: "ViewGenre") -> BaseItemDto:
        gid = await self._ids.to_jf("genre", genre_slug(g.name))
        return BaseItemDto(
            Id=gid, Name=g.name, ServerId=self._sid, Type="MusicGenre",
            IsFolder=True, MediaType="Unknown", ChildCount=g.song_count,
            SortName=g.name,
            UserData=self._user_data(gid, starred_at=None, play_count=None),
        )
