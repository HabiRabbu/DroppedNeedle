"""Tests for discovery features across Navidrome, Jellyfin, and Plex."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from api.v1.schemas.jellyfin import JellyfinTrackInfo
from api.v1.schemas.navidrome import NavidromeTrackInfo
from api.v1.schemas.plex import PlexDiscoveryAlbum, PlexDiscoveryHub, PlexDiscoveryResponse
from repositories.jellyfin_models import JellyfinItem
from repositories.navidrome_models import SubsonicSong
from services.jellyfin_library_service import JellyfinLibraryService
from services.navidrome_library_service import NavidromeLibraryService
from services.plex_library_service import PlexLibraryService


def _make_navidrome_service() -> tuple[NavidromeLibraryService, MagicMock]:
    repo = MagicMock()
    repo.get_random_songs = AsyncMock(return_value=[])
    prefs = MagicMock()
    prefs.get_advanced_settings.return_value = MagicMock()
    service = NavidromeLibraryService(navidrome_repo=repo, preferences_service=prefs)
    return service, repo


def _song(id: str = "s1", title: str = "Song", album: str = "Album",
          artist: str = "Artist", track: int = 1, duration: int = 200,
          suffix: str = "mp3", bit_rate: int = 320) -> SubsonicSong:
    return SubsonicSong(
        id=id, title=title, album=album, artist=artist,
        track=track, duration=duration, suffix=suffix, bitRate=bit_rate,
    )


def _make_jellyfin_service() -> tuple[JellyfinLibraryService, MagicMock]:
    repo = MagicMock()
    repo.is_configured.return_value = True
    repo.get_instant_mix = AsyncMock(return_value=[])
    repo.get_instant_mix_by_artist = AsyncMock(return_value=[])
    repo.get_instant_mix_by_genre = AsyncMock(return_value=[])
    repo.get_image_url = MagicMock(return_value=None)
    prefs = MagicMock()
    prefs.get_advanced_settings.return_value = MagicMock()
    service = JellyfinLibraryService(jellyfin_repo=repo, preferences_service=prefs)
    return service, repo


def _jf_item(id: str = "jf-1", name: str = "Track", type: str = "Audio",
             artist_name: str = "Artist", album: str = "Album",
             album_id: str = "alb-1", ticks: int = 3_000_000_000,
             index: int = 1) -> JellyfinItem:
    return JellyfinItem(
        id=id, name=name, type=type,
        artist_name=artist_name, album_name=album, album_id=album_id,
        duration_ticks=ticks, index_number=index,
    )


def _make_plex_service(section_ids: list[str] | None = None) -> tuple[PlexLibraryService, MagicMock]:
    repo = MagicMock()
    repo.get_hubs = AsyncMock(return_value=[])
    type(repo).stats_ttl = PropertyMock(return_value=600)
    prefs = MagicMock()
    ids = section_ids if section_ids is not None else ["1"]
    prefs.get_plex_connection_raw.return_value = MagicMock(
        enabled=True, plex_url="http://plex:32400", plex_token="tok",
        music_library_ids=ids,
    )
    prefs.get_advanced_settings.return_value = MagicMock()
    service = PlexLibraryService(plex_repo=repo, preferences_service=prefs)
    return service, repo


class TestNavidromeRandomSongs:
    @pytest.mark.asyncio
    async def test_returns_mapped_tracks(self):
        service, repo = _make_navidrome_service()
        repo.get_random_songs = AsyncMock(return_value=[
            _song(id="s1", title="Track A"),
            _song(id="s2", title="Track B"),
        ])
        tracks = await service.get_random_songs(size=10)
        assert len(tracks) == 2
        assert tracks[0].title == "Track A"
        assert tracks[1].navidrome_id == "s2"
        repo.get_random_songs.assert_awaited_once_with(
            size=10, genre=None, music_folder_ids=None
        )

    @pytest.mark.asyncio
    async def test_forwards_genre_filter(self):
        service, repo = _make_navidrome_service()
        repo.get_random_songs = AsyncMock(return_value=[_song()])
        await service.get_random_songs(size=5, genre="Rock")
        repo.get_random_songs.assert_awaited_once_with(
            size=5, genre="Rock", music_folder_ids=None
        )

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        service, repo = _make_navidrome_service()
        repo.get_random_songs = AsyncMock(side_effect=Exception("fail"))
        result = await service.get_random_songs()
        assert result == []

    @pytest.mark.asyncio
    async def test_default_size_is_20(self):
        service, repo = _make_navidrome_service()
        repo.get_random_songs = AsyncMock(return_value=[])
        await service.get_random_songs()
        repo.get_random_songs.assert_awaited_once_with(
            size=20, genre=None, music_folder_ids=None
        )


class TestJellyfinInstantMix:
    @pytest.mark.asyncio
    async def test_instant_mix_returns_tracks(self):
        service, repo = _make_jellyfin_service()
        repo.get_instant_mix = AsyncMock(return_value=[
            _jf_item(id="t1", name="Mix Track 1"),
            _jf_item(id="t2", name="Mix Track 2"),
        ])
        tracks = await service.get_instant_mix("album-1", limit=20)
        assert len(tracks) == 2
        assert tracks[0].title == "Mix Track 1"
        repo.get_instant_mix.assert_awaited_once_with("album-1", limit=20)

    @pytest.mark.asyncio
    async def test_instant_mix_returns_empty_on_error(self):
        service, repo = _make_jellyfin_service()
        repo.get_instant_mix = AsyncMock(side_effect=Exception("boom"))
        result = await service.get_instant_mix("album-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_instant_mix_by_artist(self):
        service, repo = _make_jellyfin_service()
        repo.get_instant_mix_by_artist = AsyncMock(return_value=[_jf_item()])
        tracks = await service.get_instant_mix_by_artist("artist-1", limit=30)
        assert len(tracks) == 1
        repo.get_instant_mix_by_artist.assert_awaited_once_with("artist-1", limit=30)

    @pytest.mark.asyncio
    async def test_instant_mix_by_artist_error(self):
        service, repo = _make_jellyfin_service()
        repo.get_instant_mix_by_artist = AsyncMock(side_effect=Exception("err"))
        result = await service.get_instant_mix_by_artist("a1")
        assert result == []

    @pytest.mark.asyncio
    async def test_instant_mix_by_genre(self):
        service, repo = _make_jellyfin_service()
        repo.get_instant_mix_by_genre = AsyncMock(return_value=[
            _jf_item(id="g1"), _jf_item(id="g2"),
        ])
        tracks = await service.get_instant_mix_by_genre("Rock", limit=40)
        assert len(tracks) == 2
        repo.get_instant_mix_by_genre.assert_awaited_once_with("Rock", limit=40)

    @pytest.mark.asyncio
    async def test_instant_mix_by_genre_error(self):
        service, repo = _make_jellyfin_service()
        repo.get_instant_mix_by_genre = AsyncMock(side_effect=Exception("err"))
        result = await service.get_instant_mix_by_genre("Jazz")
        assert result == []

    @pytest.mark.asyncio
    async def test_instant_mix_converts_ticks_to_seconds(self):
        service, repo = _make_jellyfin_service()
        repo.get_instant_mix = AsyncMock(return_value=[
            _jf_item(ticks=5_000_000_000),
        ])
        tracks = await service.get_instant_mix("item-1")
        assert tracks[0].duration_seconds == pytest.approx(500.0)


class TestPlexDiscoveryHubs:
    @pytest.mark.asyncio
    async def test_returns_album_hubs(self):
        service, repo = _make_plex_service()
        repo.get_hubs = AsyncMock(return_value=[
            {
                "type": "album",
                "title": "Recently Added",
                "Metadata": [
                    {
                        "ratingKey": "123",
                        "title": "Great Album",
                        "parentTitle": "Cool Artist",
                        "year": 2024,
                        "thumb": "/library/metadata/123/thumb",
                    }
                ],
            }
        ])
        result = await service.get_discovery_hubs(count=5)
        assert len(result.hubs) == 1
        assert result.hubs[0].title == "Recently Added"
        assert len(result.hubs[0].albums) == 1
        assert result.hubs[0].albums[0].name == "Great Album"
        assert result.hubs[0].albums[0].artist_name == "Cool Artist"

    @pytest.mark.asyncio
    async def test_filters_non_album_hubs(self):
        service, repo = _make_plex_service()
        repo.get_hubs = AsyncMock(return_value=[
            {"type": "artist", "title": "Top Artists", "Metadata": [{"ratingKey": "1", "title": "A"}]},
            {"type": "album", "title": "New Albums", "Metadata": [
                {"ratingKey": "2", "title": "B", "parentTitle": "ArtB", "year": 2023, "thumb": "/t"},
            ]},
        ])
        result = await service.get_discovery_hubs()
        assert len(result.hubs) == 1
        assert result.hubs[0].title == "New Albums"

    @pytest.mark.asyncio
    async def test_skips_empty_hubs(self):
        service, repo = _make_plex_service()
        repo.get_hubs = AsyncMock(return_value=[
            {"type": "album", "title": "Empty Hub", "Metadata": []},
        ])
        result = await service.get_discovery_hubs()
        assert len(result.hubs) == 0

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        service, repo = _make_plex_service()
        repo.get_hubs = AsyncMock(side_effect=Exception("timeout"))
        result = await service.get_discovery_hubs()
        assert result.hubs == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_section(self):
        service, repo = _make_plex_service(section_ids=[])
        result = await service.get_discovery_hubs()
        assert result.hubs == []
        repo.get_hubs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_image_url_includes_cover_proxy(self):
        service, repo = _make_plex_service()
        repo.get_hubs = AsyncMock(return_value=[
            {
                "type": "album",
                "title": "Hub",
                "Metadata": [
                    {"ratingKey": "9", "title": "X", "parentTitle": "Y", "thumb": "/lib/9/thumb"},
                ],
            }
        ])
        result = await service.get_discovery_hubs()
        assert "/api/v1/plex/thumb/" in result.hubs[0].albums[0].image_url

    @pytest.mark.asyncio
    async def test_no_thumb_gives_none_image(self):
        service, repo = _make_plex_service()
        repo.get_hubs = AsyncMock(return_value=[
            {
                "type": "album",
                "title": "Hub",
                "Metadata": [
                    {"ratingKey": "10", "title": "NoThumb", "parentTitle": "A"},
                ],
            }
        ])
        result = await service.get_discovery_hubs()
        assert result.hubs[0].albums[0].image_url is None
