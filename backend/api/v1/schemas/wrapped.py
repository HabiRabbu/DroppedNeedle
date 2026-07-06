from infrastructure.msgspec_fastapi import AppStruct


class WrappedUserSummary(AppStruct):
    id: str
    display_name: str
    has_listenbrainz: bool
    email: str | None = None


class WrappedUsersResponse(AppStruct):
    year: int
    users: list[WrappedUserSummary]


class WrappedArtist(AppStruct):
    name: str
    listen_count: int
    artist_mbid: str | None = None


class WrappedTrack(AppStruct):
    name: str
    artist_name: str
    listen_count: int


class WrappedAlbum(AppStruct):
    name: str
    artist_name: str
    listen_count: int
    mbid: str | None = None


class WrappedGenre(AppStruct):
    genre: str
    listen_count: int


class UserWrappedResponse(AppStruct):
    user_id: str
    display_name: str
    year: int
    has_data: bool
    top_artists: list[WrappedArtist]
    top_tracks: list[WrappedTrack]
    top_albums: list[WrappedAlbum]
    top_genres: list[WrappedGenre]
    loved_tracks_count: int
    total_listens_estimated: int


class WrappedLeaderboardEntry(AppStruct):
    display_name: str
    listen_count: int


class ServerWrappedResponse(AppStruct):
    year: int
    total_users_tracked: int
    total_listens_estimated: int
    leaderboard: list[WrappedLeaderboardEntry]
    top_artist_sitewide: WrappedArtist | None = None
    top_album_sitewide: WrappedAlbum | None = None
