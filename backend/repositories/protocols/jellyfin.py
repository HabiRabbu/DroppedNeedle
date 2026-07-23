from typing import Any, Protocol

from repositories.jellyfin_models import (
    JellyfinItem,
    JellyfinLyrics,
    JellyfinSession,
    JellyfinUser,
    PlaybackUrlResult,
)
from repositories.navidrome_models import StreamProxyResult


class JellyfinRepositoryProtocol(Protocol):
    def is_configured(self) -> bool: ...

    def configure(self, base_url: str, api_key: str, user_id: str = "") -> None: ...

    async def validate_connection(self) -> tuple[bool, str]: ...

    async def refresh_library(self) -> None: ...

    async def get_users(self) -> list[JellyfinUser]: ...

    async def fetch_users_direct(self) -> list[JellyfinUser]: ...

    async def get_current_user(self) -> JellyfinUser | None: ...

    async def get_recently_played(
        self, user_id: str | None = None, limit: int = 20, ttl_seconds: int = 300
    ) -> list[JellyfinItem]: ...

    async def get_favorite_artists(
        self, user_id: str | None = None, limit: int = 20
    ) -> list[JellyfinItem]: ...

    async def get_favorite_albums(
        self, user_id: str | None = None, limit: int = 20, ttl_seconds: int = 300
    ) -> list[JellyfinItem]: ...

    async def get_most_played_artists(
        self, user_id: str | None = None, limit: int = 20
    ) -> list[JellyfinItem]: ...

    async def get_most_played_albums(
        self, user_id: str | None = None, limit: int = 20
    ) -> list[JellyfinItem]: ...

    async def get_recently_added(
        self, user_id: str | None = None, limit: int = 20
    ) -> list[JellyfinItem]: ...

    async def get_genres(
        self, user_id: str | None = None, ttl_seconds: int = 3600
    ) -> list[str]: ...

    async def get_filter_facets(
        self, user_id: str | None = None, ttl_seconds: int = 3600
    ) -> dict[str, Any]: ...

    async def get_artists_by_genre(
        self, genre: str, user_id: str | None = None, limit: int = 50
    ) -> list[JellyfinItem]: ...

    def get_image_url(
        self, item_id: str, image_tag: str | None = None
    ) -> str | None: ...

    def get_auth_headers(self) -> dict[str, str]: ...

    async def get_albums(
        self,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "SortName",
        sort_order: str = "Ascending",
        genre: str | None = None,
        year: int | None = None,
        tags: str | None = None,
        studios: str | None = None,
    ) -> tuple[list[JellyfinItem], int]: ...

    async def get_album_tracks(self, album_id: str) -> list[JellyfinItem]: ...

    async def get_album_detail(self, album_id: str) -> JellyfinItem | None: ...

    async def get_album_by_mbid(self, musicbrainz_id: str) -> JellyfinItem | None: ...

    async def get_artist_by_mbid(self, musicbrainz_id: str) -> JellyfinItem | None: ...

    async def get_artists(
        self, limit: int = 50, offset: int = 0
    ) -> list[JellyfinItem]: ...

    async def build_mbid_index(self) -> dict[str, str]: ...

    async def search_items(
        self,
        query: str,
        item_types: str = "MusicAlbum,Audio,MusicArtist",
    ) -> list[JellyfinItem]: ...

    async def get_library_stats(self, ttl_seconds: int = 600) -> dict[str, Any]: ...

    async def get_playback_url(self, item_id: str) -> PlaybackUrlResult: ...

    async def get_playback_info(self, item_id: str) -> dict[str, Any]: ...

    async def report_playback_start(
        self, item_id: str, play_session_id: str, play_method: str = "Transcode"
    ) -> None: ...

    async def report_playback_progress(
        self,
        item_id: str,
        play_session_id: str,
        position_ticks: int,
        is_paused: bool,
    ) -> None: ...

    async def report_playback_stopped(
        self, item_id: str, play_session_id: str, position_ticks: int
    ) -> None: ...

    async def proxy_head_stream(self, item_id: str) -> StreamProxyResult: ...

    async def proxy_get_stream(
        self, item_id: str, range_header: str | None = None
    ) -> StreamProxyResult: ...

    async def get_instant_mix(
        self, item_id: str, limit: int = 50
    ) -> list[JellyfinItem]: ...

    async def get_instant_mix_by_artist(
        self, artist_id: str, limit: int = 50
    ) -> list[JellyfinItem]: ...

    async def get_instant_mix_by_genre(
        self, genre_name: str, limit: int = 50
    ) -> list[JellyfinItem]: ...

    async def get_sessions(self) -> list[JellyfinSession]: ...

    async def get_similar_items(
        self, item_id: str, limit: int = 10
    ) -> list[JellyfinItem]: ...

    async def get_lyrics(self, item_id: str) -> JellyfinLyrics | None: ...

    async def get_playlists(
        self, user_id: str | None = None, limit: int = 50
    ) -> list[JellyfinItem]: ...

    async def get_playlist(
        self, playlist_id: str, user_id: str | None = None
    ) -> JellyfinItem | None: ...

    async def get_playlist_items(
        self, playlist_id: str, user_id: str | None = None, limit: int = 1000
    ) -> list[JellyfinItem]: ...

    async def proxy_image(self, item_id: str, size: int = 500) -> tuple[bytes, str]: ...
