"""T0.7 - LibraryViewService returns neutral View DTOs + per-user starred_at."""

import pytest

from infrastructure.persistence.auth_store import UserRecord
from services.compat.view_models import ViewAlbum, ViewArtist, ViewTrack
from services.native.library_manager import _synth_artist_mbid

pytestmark = pytest.mark.asyncio

_ALICE = UserRecord(
    id="user-alice", display_name="Alice", role="user",
    created_at="2024-01-01T00:00:00Z", username="alice",
)


async def test_get_artists_returns_view_artist_with_synth_mbid(library_view_service):
    artists, total = await library_view_service.get_artists()
    assert total == 1
    assert isinstance(artists[0], ViewArtist)
    assert artists[0].name == "Radiohead"
    # MBID-less artist -> synthesised, non-empty id
    assert artists[0].artist_mbid == _synth_artist_mbid("Radiohead")


async def test_get_albums_returns_view_album(library_view_service):
    albums, total = await library_view_service.get_albums()
    assert total == 1
    assert isinstance(albums[0], ViewAlbum)
    assert albums[0].title == "OK Computer"
    assert albums[0].rg_mbid == "b1392450-e666-3926-a536-22c65f834433"


async def test_get_album_detail_aggregates_tracks(library_view_service, seeded_library):
    _db, _lm, ids = seeded_library
    album = await library_view_service.get_album(ids["rg"])
    assert album is not None
    assert album.track_count == 2
    assert album.genre == "Alternative Rock"          # dominant genre
    assert album.artist_mbid == _synth_artist_mbid("Radiohead")
    assert album.total_duration_seconds == pytest.approx(403.0)  # 201 + 202


async def test_get_album_tracks_are_complete_view_tracks(library_view_service, seeded_library):
    _db, _lm, ids = seeded_library
    tracks = await library_view_service.get_album_tracks(ids["rg"])
    assert len(tracks) == 2
    t = tracks[0]
    assert isinstance(t, ViewTrack)
    assert t.genre == "Alternative Rock"
    assert t.channels == 2
    assert t.sample_rate == 44100
    assert t.artist_mbid == _synth_artist_mbid("Radiohead")
    assert t.rg_mbid == ids["rg"]


async def test_get_track_single(library_view_service, seeded_library):
    _db, _lm, ids = seeded_library
    track = await library_view_service.get_track(ids["tracks"][0])
    assert track is not None
    assert track.file_id == ids["tracks"][0]
    assert track.title == "Airbag"
    assert track.file_path  # populated for the stream layer


async def test_get_track_missing_returns_none(library_view_service):
    assert await library_view_service.get_track("does-not-exist") is None


async def test_get_tracks_page(library_view_service):
    tracks, total = await library_view_service.get_tracks_page()
    assert total == 2
    assert {t.title for t in tracks} == {"Airbag", "Paranoid Android"}


async def test_starred_at_filled_for_user(library_view_service, seeded_library, favorites_service):
    _db, _lm, ids = seeded_library
    fav_id = ids["tracks"][0]
    await favorites_service.add("user-alice", "track", fav_id)

    # anonymous -> no starred_at
    anon = await library_view_service.get_track(fav_id)
    assert anon.starred_at is None

    # with user -> starred_at filled on the favorited track only
    tracks = await library_view_service.get_album_tracks(ids["rg"], user=_ALICE)
    by_id = {t.file_id: t for t in tracks}
    assert by_id[fav_id].starred_at is not None
    assert by_id[ids["tracks"][1]].starred_at is None
