from infrastructure.msgspec_fastapi import AppStruct


class SimilarArtist(AppStruct):
    musicbrainz_id: str
    name: str
    listen_count: int = 0
    in_library: bool = False
    image_url: str | None = None


class SimilarArtistsResponse(AppStruct):
    similar_artists: list[SimilarArtist] = []
    source: str = "listenbrainz"
    configured: bool = True


class TopSong(AppStruct):
    title: str
    artist_name: str
    recording_mbid: str | None = None
    release_group_mbid: str | None = None
    original_release_mbid: str | None = None
    release_name: str | None = None
    listen_count: int = 0
    disc_number: int | None = None
    track_number: int | None = None


class TopSongsResponse(AppStruct):
    songs: list[TopSong] = []
    source: str = "listenbrainz"
    configured: bool = True


class TopAlbum(AppStruct):
    title: str
    artist_name: str
    release_group_mbid: str | None = None
    year: int | None = None
    listen_count: int = 0
    in_library: bool = False
    requested: bool = False
    cover_url: str | None = None


class TopAlbumsResponse(AppStruct):
    albums: list[TopAlbum] = []
    source: str = "listenbrainz"
    configured: bool = True


class DiscoveryAlbum(AppStruct):
    musicbrainz_id: str
    title: str
    artist_name: str
    artist_id: str | None = None
    year: int | None = None
    in_library: bool = False
    requested: bool = False
    cover_url: str | None = None


class SimilarAlbumsResponse(AppStruct):
    albums: list[DiscoveryAlbum] = []
    source: str = "listenbrainz"
    configured: bool = True


class MoreByArtistResponse(AppStruct):
    albums: list[DiscoveryAlbum] = []
    artist_name: str = ""
