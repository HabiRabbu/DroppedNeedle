"""Home page section builders: pure data transformation, no I/O."""

from __future__ import annotations

from typing import Any

from api.v1.schemas.home import HomeSection, HomeTrack, ServicePrompt
from api.v1.schemas.library import LibraryAlbum
from services.home_transformers import HomeDataTransformers


class HomeSectionBuilders:
    def __init__(self, transformers: HomeDataTransformers):
        self._transformers = transformers

    def build_recently_added_section(
        self, recently_imported: list[LibraryAlbum]
    ) -> HomeSection:
        return HomeSection(
            title="Recently Added",
            type="albums",
            items=[self._transformers.library_album_to_home(a) for a in recently_imported[:15]],
            source="library",
        )

    def build_library_artists_section(self, library_artists: list[dict]) -> HomeSection:
        sorted_artists = sorted(
            library_artists, key=lambda x: x.get("album_count", 0), reverse=True
        )[:15]
        items = [
            a for a in (self._transformers.library_artist_to_home(artist) for artist in sorted_artists)
            if a is not None
        ]
        return HomeSection(title="Your Artists", type="artists", items=items, source="library")

    def build_library_albums_section(self, library_albums: list[LibraryAlbum]) -> HomeSection:
        sorted_albums = sorted(
            library_albums, key=lambda x: (x.year or 0, x.album or ""), reverse=True
        )[:15]
        return HomeSection(
            title="Your Albums",
            type="albums",
            items=[self._transformers.library_album_to_home(a) for a in sorted_albums],
            source="library",
        )

    def build_trending_artists_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection:
        artists = results.get("lb_trending_artists") or []
        items = [
            a for a in (self._transformers.lb_artist_to_home(artist, library_mbids) for artist in artists[:15])
            if a is not None
        ]
        return HomeSection(
            title="Trending Artists",
            type="artists",
            items=items,
            source="listenbrainz" if artists else None,
        )

    def build_popular_albums_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection:
        albums = results.get("lb_trending_albums") or []
        return HomeSection(
            title="Popular Right Now",
            type="albums",
            items=[self._transformers.lb_release_to_home(a, library_mbids) for a in albums[:15]],
            source="listenbrainz" if albums else None,
        )

    def build_lb_user_top_albums_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection | None:
        release_groups = results.get("lb_user_top_rgs") or []
        if not release_groups:
            return None
        items = [
            self._transformers.lb_release_to_home(rg, library_mbids)
            for rg in release_groups[:15]
        ]
        return HomeSection(
            title="Your Top Albums",
            type="albums",
            items=items,
            source="listenbrainz",
        )

    def build_genre_list_section(
        self, library_albums: list[LibraryAlbum], lb_genres: list | None = None
    ) -> HomeSection:
        genres = self._transformers.extract_genres_from_library(library_albums, lb_genres)
        source = "listenbrainz" if lb_genres else ("library" if library_albums else None)
        return HomeSection(title="Browse by Genre", type="genres", items=genres, source=source)

    def build_fresh_releases_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection | None:
        releases = results.get("lb_fresh")
        if not releases:
            return None
        return HomeSection(
            title="New From Artists You Follow",
            type="albums",
            items=[self._transformers.lb_release_to_home(r, library_mbids) for r in releases[:15]],
            source="listenbrainz",
        )

    def build_recommended_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection | None:
        artists = results.get("lb_top_artists")
        if not artists:
            return None
        items = [
            a for a in (self._transformers.lb_artist_to_home(artist, library_mbids) for artist in artists[:15])
            if a is not None
        ]
        return HomeSection(
            title="Based on Your Listening", type="artists", items=items, source="listenbrainz"
        )

    def build_listenbrainz_recent_section(self, results: dict[str, Any]) -> HomeSection | None:
        listens = results.get("lb_listens") or []
        if not listens:
            return None
        items = [
            self._transformers.lb_listen_to_home_track(listen)
            for listen in listens[:15]
        ]
        return HomeSection(
            title="Recently Scrobbled",
            type="tracks",
            items=items,
            source="listenbrainz",
        )

    def build_play_history_recent_section(self, records: list[Any]) -> HomeSection | None:
        if not records:
            return None
        items = [
            HomeTrack(
                name=r.track_name,
                mbid=r.recording_mbid,
                artist_name=r.artist_name,
                album_name=r.album_name,
                listened_at=r.played_at,
            )
            for r in records[:15]
        ]
        return HomeSection(
            title="Recently Played",
            type="tracks",
            items=items,
            source="local",
        )

    def build_listenbrainz_favorites_section(self, results: dict[str, Any]) -> HomeSection | None:
        loved = results.get("lb_loved") or []
        if not loved:
            return None
        items = [
            self._transformers.lb_feedback_to_home_track(recording)
            for recording in loved[:15]
        ]
        return HomeSection(
            title="Your Favorites",
            type="tracks",
            items=items,
            source="listenbrainz",
        )

    def build_lastfm_trending_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection:
        artists = results.get("lfm_global_top_artists") or []
        items = [
            a for a in (
                self._transformers.lastfm_artist_to_home(artist, library_mbids)
                for artist in artists[:15]
            )
            if a is not None
        ]
        return HomeSection(
            title="Trending Artists",
            type="artists",
            items=items,
            source="lastfm" if artists else None,
        )

    def build_lastfm_top_albums_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection:
        albums = results.get("lfm_top_albums") or []
        items = [
            a for a in (
                self._transformers.lastfm_album_to_home(album, library_mbids)
                for album in albums[:15]
            )
            if a is not None
        ]
        return HomeSection(
            title="Your Top Albums",
            type="albums",
            items=items,
            source="lastfm" if albums else None,
        )

    def build_lastfm_recommended_section(
        self, results: dict[str, Any], library_mbids: set[str]
    ) -> HomeSection | None:
        artists = results.get("lfm_top_artists") or []
        if not artists:
            return None
        items = [
            a for a in (
                self._transformers.lastfm_artist_to_home(artist, library_mbids)
                for artist in artists[:15]
            )
            if a is not None
        ]
        if not items:
            return None
        return HomeSection(
            title="Based on Your Listening",
            type="artists",
            items=items,
            source="lastfm",
        )

    def build_lastfm_recent_section(self, results: dict[str, Any]) -> HomeSection | None:
        tracks = results.get("lfm_recent") or []
        if not tracks:
            return None
        items = [
            self._transformers.lastfm_recent_to_home_track(track)
            for track in tracks[:15]
        ]
        if not items:
            return None
        return HomeSection(
            title="Recently Scrobbled",
            type="tracks",
            items=items,
            source="lastfm",
        )

    def build_lastfm_favorites_section(self, results: dict[str, Any]) -> HomeSection | None:
        tracks = results.get("lfm_loved") or []
        if not tracks:
            return None
        items = [
            self._transformers.lastfm_loved_to_home_track(track)
            for track in tracks[:15]
        ]
        return HomeSection(
            title="Your Favorites",
            type="tracks",
            items=items,
            source="lastfm",
        )

    @staticmethod
    def build_service_prompts(
        lb_enabled: bool,
        download_client_configured: bool = True,
        lfm_enabled: bool = False,
    ) -> list[ServicePrompt]:
        prompts = []
        if not download_client_configured:
            prompts.append(ServicePrompt(
                service="download-client",
                title="Connect a download client",
                description="DroppedNeedle needs a download source (slskd for Soulseek, or SABnzbd + an indexer for Usenet) to fetch the albums and tracks you request. Add one in Settings to start downloading into your library.",
                icon="🎶",
                color="accent",
                features=["Album & track requests", "Automatic downloads", "Direct-to-library imports", "Queue management"],
            ))
        if not lb_enabled and not lfm_enabled:
            prompts.append(ServicePrompt(
                service="listenbrainz",
                title="Connect ListenBrainz",
                description="Get recommendations from your listening history, spot new releases from artists you already love, and keep an eye on your top genres. Connect Last.fm too if you want global listener stats.",
                icon="🎵",
                color="primary",
                features=["Personalized recommendations", "New release alerts", "Listening stats", "Top genres"],
            ))
        if not lfm_enabled and not lb_enabled:
            prompts.append(ServicePrompt(
                service="lastfm",
                title="Connect Last.fm",
                description="Track your listening, compare stats, and discover music that matches your taste.",
                icon="🎸",
                color="primary",
                features=["Scrobbling", "Global listener stats", "Artist recommendations", "Play history"],
            ))
        return prompts
