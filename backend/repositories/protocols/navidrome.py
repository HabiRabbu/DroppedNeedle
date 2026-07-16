from typing import Protocol

from repositories.navidrome_models import (
    SubsonicAlbum,
    SubsonicAlbumInfo,
    SubsonicArtist,
    SubsonicArtistIndex,
    SubsonicArtistInfo,
    SubsonicGenre,
    SubsonicLyrics,
    SubsonicMusicFolder,
    SubsonicNowPlayingEntry,
    SubsonicPlaylist,
    SubsonicSearchResult,
    SubsonicSong,
    StreamProxyResult,
)


class NavidromeRepositoryProtocol(Protocol):

    @property
    def server_identity(self) -> str:
        ...

    def is_configured(self) -> bool:
        ...

    def configure(self, url: str, username: str, password: str) -> None:
        ...

    async def ping(self) -> bool:
        ...

    async def get_album_list(
        self,
        type: str,
        size: int = 20,
        offset: int = 0,
        genre: str | None = None,
        from_year: int | None = None,
        to_year: int | None = None,
        music_folder_ids: tuple[str, ...] | None = None,
    ) -> list[SubsonicAlbum]:
        ...

    async def get_album(self, id: str) -> SubsonicAlbum:
        ...

    async def get_artists(
        self, music_folder_ids: tuple[str, ...] | None = None
    ) -> list[SubsonicArtist]:
        ...

    async def get_artist(self, id: str) -> SubsonicArtist:
        ...

    async def get_song(self, id: str) -> SubsonicSong:
        ...

    async def search(
        self,
        query: str,
        artist_count: int = 20,
        album_count: int = 20,
        song_count: int = 20,
        music_folder_ids: tuple[str, ...] | None = None,
    ) -> SubsonicSearchResult:
        ...

    async def get_starred(
        self, music_folder_ids: tuple[str, ...] | None = None
    ) -> SubsonicSearchResult:
        ...

    async def get_genres(self) -> list[SubsonicGenre]:
        ...

    async def get_artists_index(
        self, music_folder_ids: tuple[str, ...] | None = None
    ) -> list[SubsonicArtistIndex]:
        ...

    async def get_songs_by_genre(
        self,
        genre: str,
        count: int = 50,
        offset: int = 0,
        music_folder_ids: tuple[str, ...] | None = None,
    ) -> list[SubsonicSong]:
        ...

    async def search_songs(
        self,
        query: str = "",
        count: int = 50,
        offset: int = 0,
        music_folder_ids: tuple[str, ...] | None = None,
    ) -> list[SubsonicSong]:
        ...

    async def get_music_folders(self) -> list[SubsonicMusicFolder]:
        ...

    async def get_playlists(self) -> list[SubsonicPlaylist]:
        ...

    async def get_playlist(self, id: str) -> SubsonicPlaylist:
        ...

    async def get_random_songs(
        self,
        size: int = 20,
        genre: str | None = None,
        music_folder_ids: tuple[str, ...] | None = None,
    ) -> list[SubsonicSong]:
        ...

    async def scrobble(self, id: str, time_ms: int | None = None) -> bool:
        ...

    async def validate_connection(self) -> tuple[bool, str]:
        ...

    async def clear_cache(self) -> None:
        ...

    def build_stream_url(self, song_id: str) -> str:
        ...

    async def proxy_head_stream(self, song_id: str) -> StreamProxyResult:
        ...

    async def proxy_get_stream(
        self, song_id: str, range_header: str | None = None
    ) -> StreamProxyResult:
        ...

    async def now_playing(self, id: str) -> bool:
        ...

    async def get_now_playing(self) -> list[SubsonicNowPlayingEntry]:
        ...

    async def get_top_songs(
        self, artist_name: str, count: int = 20
    ) -> list[SubsonicSong]:
        ...

    async def get_similar_songs(
        self, song_id: str, count: int = 20
    ) -> list[SubsonicSong]:
        ...

    async def get_artist_info(self, artist_id: str) -> SubsonicArtistInfo | None:
        ...

    async def get_album_info(self, album_id: str) -> SubsonicAlbumInfo | None:
        ...

    async def get_lyrics(self, artist: str, title: str) -> SubsonicLyrics | None:
        ...

    async def get_lyrics_by_song_id(self, song_id: str) -> SubsonicLyrics | None:
        ...
