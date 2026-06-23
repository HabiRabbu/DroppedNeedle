from datetime import UTC, datetime

from api.v1.schemas.home import HomeArtist, HomeAlbum, HomeGenre, HomeTrack
from api.v1.schemas.library import LibraryAlbum
from repositories.lastfm_models import (
    LastFmAlbum,
    LastFmArtist,
    LastFmLovedTrack,
    LastFmRecentTrack,
    LastFmSimilarArtist,
)
from repositories.listenbrainz_models import ListenBrainzFeedbackRecording, ListenBrainzListen
from repositories.protocols import (
    ListenBrainzArtist,
    ListenBrainzReleaseGroup,
    JellyfinRepositoryProtocol,
)
from repositories.jellyfin_models import JellyfinItem


class HomeDataTransformers:
    def __init__(self, jellyfin_repo: JellyfinRepositoryProtocol | None = None):
        self._jf_repo = jellyfin_repo

    @staticmethod
    def _cover_url(release_mbid: str | None) -> str | None:
        if release_mbid:
            return f"/api/v1/covers/release/{release_mbid}?size=250"
        return None

    def library_album_to_home(self, album: LibraryAlbum) -> HomeAlbum:
        return HomeAlbum(
            mbid=album.musicbrainz_id,
            name=album.album or "Unknown Album",
            artist_name=album.artist,
            artist_mbid=album.artist_mbid,
            image_url=album.cover_url,
            release_date=str(album.year) if album.year else None,
            in_library=True,
        )

    def library_artist_to_home(self, artist_data: dict) -> HomeArtist | None:
        mbid = artist_data.get("mbid")
        if not mbid:
            return None
        return HomeArtist(
            mbid=mbid,
            name=artist_data.get("name", "Unknown Artist"),
            image_url=None,
            listen_count=artist_data.get("album_count"),
            in_library=True,
        )

    def lb_artist_to_home(
        self,
        artist: ListenBrainzArtist,
        library_mbids: set[str]
    ) -> HomeArtist | None:
        mbid = artist.artist_mbids[0] if artist.artist_mbids else None
        if not mbid:
            return None
        return HomeArtist(
            mbid=mbid,
            name=artist.artist_name,
            image_url=None,
            listen_count=artist.listen_count,
            in_library=mbid.lower() in library_mbids,
        )

    def lb_release_to_home(
        self,
        release: ListenBrainzReleaseGroup,
        library_mbids: set[str],
    ) -> HomeAlbum:
        artist_mbid = release.artist_mbids[0] if release.artist_mbids else None
        mbid_lower = (release.release_group_mbid or "").lower()
        in_library = mbid_lower in library_mbids
        return HomeAlbum(
            mbid=release.release_group_mbid,
            name=release.release_group_name,
            artist_name=release.artist_name,
            artist_mbid=artist_mbid,
            image_url=None,
            release_date=None,
            listen_count=release.listen_count,
            in_library=in_library,
        )

    def jf_item_to_artist(
        self,
        item: JellyfinItem,
        library_mbids: set[str]
    ) -> HomeArtist | None:
        mbid = None
        if item.provider_ids:
            mbid = item.provider_ids.get("MusicBrainzArtist")

        artist_name = item.artist_name or item.name
        if not artist_name:
            return None

        image_url = None
        if self._jf_repo:
            if item.artist_id:
                image_url = self._jf_repo.get_image_url(item.artist_id, item.image_tag)
            else:
                image_url = self._jf_repo.get_image_url(item.id, item.image_tag)

        return HomeArtist(
            mbid=mbid,
            name=artist_name,
            image_url=image_url,
            listen_count=item.play_count,
            in_library=mbid.lower() in library_mbids if mbid else False,
        )

    def lastfm_artist_to_home(
        self,
        artist: LastFmArtist,
        library_mbids: set[str],
    ) -> HomeArtist | None:
        return HomeArtist(
            mbid=artist.mbid,
            name=artist.name,
            image_url=None,
            listen_count=artist.playcount,
            in_library=artist.mbid.lower() in library_mbids if artist.mbid else False,
            source="lastfm",
        )

    def lastfm_album_to_home(
        self,
        album: LastFmAlbum,
        library_mbids: set[str],
    ) -> HomeAlbum | None:
        mbid_lower = album.mbid.lower() if album.mbid else ""
        in_library = mbid_lower in library_mbids if mbid_lower else False
        return HomeAlbum(
            mbid=None,
            name=album.name,
            artist_name=album.artist_name,
            artist_mbid=None,
            image_url=album.image_url or None,
            listen_count=album.playcount,
            in_library=in_library,
            source="lastfm",
        )

    def lastfm_similar_to_home(
        self,
        similar: LastFmSimilarArtist,
        library_mbids: set[str],
    ) -> HomeArtist | None:
        return HomeArtist(
            mbid=similar.mbid,
            name=similar.name,
            image_url=None,
            in_library=similar.mbid.lower() in library_mbids if similar.mbid else False,
            source="lastfm",
        )

    def lastfm_recent_to_home(
        self,
        track: LastFmRecentTrack,
        library_mbids: set[str],
    ) -> HomeAlbum | None:
        mbid_lower = (track.album_mbid or "").lower()
        in_library = mbid_lower in library_mbids if track.album_mbid else False
        return HomeAlbum(
            mbid=track.album_mbid,
            name=track.album_name or track.track_name,
            artist_name=track.artist_name,
            artist_mbid=track.artist_mbid,
            image_url=track.image_url or None,
            in_library=in_library,
            source="lastfm",
        )

    def lb_listen_to_home_track(self, listen: ListenBrainzListen) -> HomeTrack:
        listened_at = None
        if listen.listened_at:
            listened_at = datetime.fromtimestamp(listen.listened_at, tz=UTC).isoformat()
        artist_mbid = listen.artist_mbids[0] if listen.artist_mbids else None
        image_url = self._cover_url(listen.release_mbid)
        return HomeTrack(
            mbid=listen.recording_mbid,
            name=listen.track_name,
            artist_name=listen.artist_name,
            artist_mbid=artist_mbid,
            album_name=listen.release_name,
            listen_count=None,
            listened_at=listened_at,
            image_url=image_url,
        )

    def lastfm_recent_to_home_track(self, track: LastFmRecentTrack) -> HomeTrack:
        listened_at = None
        if track.timestamp:
            listened_at = datetime.fromtimestamp(track.timestamp, tz=UTC).isoformat()
        return HomeTrack(
            mbid=None,
            name=track.track_name,
            artist_name=track.artist_name,
            artist_mbid=None,
            album_name=track.album_name or None,
            listen_count=None,
            listened_at=listened_at,
            image_url=track.image_url or None,
        )

    def lastfm_loved_to_home_track(self, track: LastFmLovedTrack) -> HomeTrack:
        return HomeTrack(
            mbid=None,
            name=track.track_name,
            artist_name=track.artist_name,
            artist_mbid=None,
            album_name=track.album_name or None,
            listen_count=None,
            listened_at=None,
            image_url=track.image_url or None,
        )

    def lb_feedback_to_home_track(self, feedback: ListenBrainzFeedbackRecording) -> HomeTrack:
        artist_mbid = feedback.artist_mbids[0] if feedback.artist_mbids else None
        image_url = self._cover_url(feedback.release_mbid)
        return HomeTrack(
            mbid=feedback.recording_mbid,
            name=feedback.track_name,
            artist_name=feedback.artist_name,
            artist_mbid=artist_mbid,
            album_name=feedback.release_name,
            listen_count=None,
            listened_at=None,
            image_url=image_url,
        )

    def extract_genres_from_library(
        self,
        albums: list[LibraryAlbum],
        lb_genres: list | None = None
    ) -> list[HomeGenre]:
        if lb_genres:
            return [
                HomeGenre(name=g.genre, listen_count=g.listen_count)
                for g in lb_genres[:20]
            ]

        default_genres = [
            "Rock", "Pop", "Hip Hop", "Electronic", "Jazz",
            "Classical", "R&B", "Country", "Metal", "Folk",
            "Blues", "Reggae", "Soul", "Punk", "Indie",
            "Alternative", "Dance", "Soundtrack", "World", "Latin"
        ]

        return [HomeGenre(name=g) for g in default_genres]

    @staticmethod
    def get_range_label(range_key: str) -> str:
        labels = {
            "this_week": "This Week",
            "this_month": "This Month",
            "this_year": "This Year",
            "all_time": "All Time",
            "week": "This Week",
            "month": "This Month",
            "year": "This Year",
        }
        return labels.get(range_key, range_key.replace("_", " ").title())
