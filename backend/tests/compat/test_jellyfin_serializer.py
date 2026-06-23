"""T4.1 - Jellyfin BaseItemDto builder: PascalCase, ticks, UserData, ImageTags."""

import msgspec
import pytest

from api.compat.jellyfin.builders import JellyfinBuilder, ticks
from api.compat.jellyfin.models import SERVER_ID
from services.compat.view_models import ViewAlbum, ViewArtist, ViewTrack

_aio = pytest.mark.asyncio


class _Cover:
    def __init__(self, album_tag=None, artist_tag=None):
        self._album_tag = album_tag
        self._artist_tag = artist_tag

    async def get_release_group_cover_etag(self, rg, size="500"):
        return self._album_tag

    async def get_artist_image_etag(self, aid, size=None):
        return self._artist_tag


def _track(**over) -> ViewTrack:
    base = dict(
        file_id="f1", title="Airbag", album_title="OK Computer",
        rg_mbid="rg-1", artist_name="Radiohead", artist_mbid="ar-mb",
        album_artist_name="Radiohead", album_artist_mbid="ar-mb",
        track_number=1, disc_number=1, year=1997, genre="Alt Rock",
        duration_seconds=234.56, file_format="flac", sample_rate=44100,
        channels=2, bit_depth=16, recording_mbid="rec-1",
    )
    base.update(over)
    return ViewTrack(**base)


@_aio
async def test_audio_pascalcase_and_ticks(compat_id_map_service):
    b = JellyfinBuilder(compat_id_map_service, _Cover(album_tag="tagX"), SERVER_ID)
    item = await b.audio(_track())
    raw = msgspec.to_builtins(item)
    for key in ("Id", "Name", "Type", "RunTimeTicks", "IndexNumber",
                "ParentIndexNumber", "AlbumId", "ImageTags", "UserData", "Container"):
        assert key in raw
    assert not any(k[:1].islower() for k in raw)  # no snake_case leakage
    assert raw["Type"] == "Audio"
    assert raw["RunTimeTicks"] == round(234.56 * 10_000_000)
    assert raw["IndexNumber"] == 1 and raw["ParentIndexNumber"] == 1
    assert raw["Container"] == "flac"
    assert raw["ServerId"] == SERVER_ID


@_aio
async def test_audio_userdata_block(compat_id_map_service):
    b = JellyfinBuilder(compat_id_map_service, _Cover(album_tag="t"), SERVER_ID)
    item = await b.audio(_track(starred_at=123.0, play_count=4))
    ud = msgspec.to_builtins(item)["UserData"]
    assert ud["IsFavorite"] is True
    assert ud["PlayCount"] == 4 and ud["Played"] is True
    assert ud["ItemId"] == item.Id and ud["Key"] == item.Id


@_aio
async def test_imagetags_present_when_art_else_absent(compat_id_map_service):
    with_art = JellyfinBuilder(compat_id_map_service, _Cover(album_tag="abc"), SERVER_ID)
    audio = await with_art.audio(_track())
    assert audio.ImageTags == {"Primary": "abc"}
    assert audio.AlbumPrimaryImageTag == "abc"

    no_art = JellyfinBuilder(compat_id_map_service, _Cover(album_tag=None), SERVER_ID)
    audio2 = await no_art.audio(_track())
    assert audio2.ImageTags == {}
    assert audio2.AlbumPrimaryImageTag is None


@_aio
async def test_album_and_artist_items(compat_id_map_service):
    b = JellyfinBuilder(compat_id_map_service, _Cover(album_tag="t", artist_tag="art"), SERVER_ID)
    album = await b.album(ViewAlbum(
        rg_mbid="rg-1", title="OK Computer", artist_name="Radiohead",
        artist_mbid="ar-mb", year=1997, track_count=12,
        total_duration_seconds=3000.0, genre="Alt Rock",
    ))
    assert album.Type == "MusicAlbum" and album.IsFolder is True
    assert album.RunTimeTicks == ticks(3000.0)
    assert album.ChildCount == 12
    assert album.AlbumArtists[0].Name == "Radiohead"
    assert album.ProviderIds["MusicBrainzReleaseGroup"] == "rg-1"

    artist = await b.artist(ViewArtist(artist_mbid="ar-mb", name="Radiohead", album_count=3))
    assert artist.Type == "MusicArtist" and artist.IsFolder is True
    assert artist.ImageTags == {"Primary": "art"}
    assert artist.ProviderIds["MusicBrainzArtist"] == "ar-mb"


@_aio
async def test_ids_round_trip_through_id_map(compat_id_map_service):
    b = JellyfinBuilder(compat_id_map_service, _Cover(), SERVER_ID)
    item = await b.audio(_track())
    assert await compat_id_map_service.from_jf(item.Id) == ("track", "f1")
    assert await compat_id_map_service.from_jf(item.AlbumId) == ("album", "rg-1")


def test_server_id_stable_32hex():
    import re

    assert re.fullmatch(r"[0-9a-f]{32}", SERVER_ID)
    # deterministic across imports
    from api.compat.jellyfin.models import SERVER_ID as again
    assert SERVER_ID == again
