"""T0.10 - compat discovery: owned-local hybrid, discover_mode-gated (Q12/Q20)."""

import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from unittest.mock import AsyncMock

from api.v1.schemas.discovery import SimilarArtist, SimilarArtistsResponse
from api.v1.schemas.settings import ConnectAppsSettings
from infrastructure.persistence.play_history_store import PlayHistoryStore
from models.audio import AudioInfo, AudioTag
from services.compat.discover_service import CompatDiscoverService

pytestmark = pytest.mark.asyncio

_A = "11111111-1111-1111-1111-111111111111"  # real-shaped MBID
_B = "22222222-2222-2222-2222-222222222222"  # related real-shaped MBID


class _FakePrefs:
    def __init__(self, mode: str) -> None:
        self._mode = mode

    def get_connect_apps_settings(self) -> ConnectAppsSettings:
        return ConnectAppsSettings(discover_mode=self._mode)


def _make_service(library_view_service, db, mode, **mocks) -> CompatDiscoverService:
    # a real PlayHistoryStore on the same db guarantees the play_history table
    # exists (mirrors production: the discover service depends on it)
    phs = PlayHistoryStore(db_path=db.db_path, write_lock=db._write_lock)
    return CompatDiscoverService(
        library_db=db,
        library_view_service=library_view_service,
        preferences_service=_FakePrefs(mode),
        play_history_store=phs,
        artist_discovery_service=mocks.get("artist_discovery"),
        client_factory=mocks.get("client_factory"),
        related_artists_fetcher=mocks.get("fetcher"),
    )


async def _seed_artist(lm, *, name, mbid, rg, title, recording_mbid):
    return await lm.upsert_file(
        Path(f"/music/{title}.flac"),
        AudioTag(
            title=title, artist=name, album=f"{name} LP", track_number=1,
            album_artist=name, year=2020, genre="Rock",
            musicbrainz_artist_id=mbid, musicbrainz_album_artist_id=mbid,
        ),
        AudioInfo(
            duration_seconds=180.0, bitrate=900, sample_rate=44100, channels=2,
            file_format="flac", file_size_bytes=1000, bit_depth=16,
        ),
        release_group_mbid=rg, recording_mbid=recording_mbid, file_mtime=1.0,
    )


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


async def test_get_top_songs_returns_most_played(
    library_view_service, seeded_library, db_path, write_lock
):
    _db, _lm, ids = seeded_library
    phs = PlayHistoryStore(db_path=db_path, write_lock=write_lock)
    # Airbag (rec-1) played 3x, Paranoid Android (rec-2) once
    for n in range(3):
        await phs.insert(
            "user-alice", track_name="Airbag", artist_name="Radiohead",
            played_at=_iso(1_700_000_000 + n), recording_mbid="rec-1",
        )
    await phs.insert(
        "user-alice", track_name="Paranoid Android", artist_name="Radiohead",
        played_at=_iso(1_700_000_100), recording_mbid="rec-2",
    )
    svc = _make_service(library_view_service, _db, "local-only")
    top = await svc.get_top_songs("Radiohead", user_id="user-alice")
    assert [t.title for t in top] == ["Airbag", "Paranoid Android"]
    # all results intersect the owned, active library
    assert all(t.file_id for t in top)


async def test_get_random_songs_filters_by_genre(library_view_service, seeded_library):
    _db, _lm, _ids = seeded_library
    svc = _make_service(library_view_service, _db, "local-only")
    hits = await svc.get_random_songs(count=10, genre="Alternative Rock")
    assert len(hits) == 2  # both Radiohead tracks
    assert await svc.get_random_songs(count=10, genre="Polka") == []


async def test_similar_local_only_same_artist_no_outbound(
    library_view_service, seeded_library
):
    db, lm, _ids = seeded_library
    await _seed_artist(lm, name="A", mbid=_A, rg="rg-a-aaaaaaaaaaaaaaaaaaaaaaaa", title="A1", recording_mbid="rec-a1")
    await _seed_artist(lm, name="B", mbid=_B, rg="rg-b-bbbbbbbbbbbbbbbbbbbbbbbb", title="B1", recording_mbid="rec-b1")
    fetcher, ad = AsyncMock(), AsyncMock()
    svc = _make_service(library_view_service, db, "local-only", fetcher=fetcher, artist_discovery=ad)
    hits = await svc.get_similar_songs(_A, user_id="user-alice")
    assert {t.title for t in hits} == {"A1"}        # same-artist only
    fetcher.assert_not_called()
    ad.get_similar_artists.assert_not_called()


async def test_similar_lazy_mb_fetches_once_then_caches(
    library_view_service, seeded_library
):
    db, lm, _ids = seeded_library
    await _seed_artist(lm, name="A", mbid=_A, rg="rg-a-aaaaaaaaaaaaaaaaaaaaaaaa", title="A1", recording_mbid="rec-a1")
    await _seed_artist(lm, name="B", mbid=_B, rg="rg-b-bbbbbbbbbbbbbbbbbbbbbbbb", title="B1", recording_mbid="rec-b1")
    fetcher = AsyncMock(return_value=[_B])
    svc = _make_service(library_view_service, db, "lazy-mb", fetcher=fetcher)

    first = await svc.get_similar_songs(_A, user_id="user-alice")
    assert {t.title for t in first} == {"A1", "B1"}   # same-artist + related
    second = await svc.get_similar_songs(_A, user_id="user-alice")
    assert {t.title for t in second} == {"A1", "B1"}
    assert fetcher.call_count == 1                    # cached on the second call


async def test_similar_lazy_mb_skips_synthetic_mbid(library_view_service, seeded_library):
    # the seeded Radiohead artist has a synthetic (dashless) id -> no MB fetch
    from services.native.library_manager import _synth_artist_mbid

    db, _lm, _ids = seeded_library
    fetcher = AsyncMock(return_value=["whatever"])
    svc = _make_service(library_view_service, db, "lazy-mb", fetcher=fetcher)
    hits = await svc.get_similar_songs(_synth_artist_mbid("Radiohead"), user_id="user-alice")
    assert {t.title for t in hits} == {"Airbag", "Paranoid Android"}
    fetcher.assert_not_called()


async def test_similar_use_scrobble_targets_routes_when_configured(
    library_view_service, seeded_library
):
    db, lm, _ids = seeded_library
    await _seed_artist(lm, name="A", mbid=_A, rg="rg-a-aaaaaaaaaaaaaaaaaaaaaaaa", title="A1", recording_mbid="rec-a1")
    await _seed_artist(lm, name="B", mbid=_B, rg="rg-b-bbbbbbbbbbbbbbbbbbbbbbbb", title="B1", recording_mbid="rec-b1")
    cf = AsyncMock()
    cf.resolve_lastfm = AsyncMock(return_value=object())  # user HAS a Last.fm target
    ad = AsyncMock()
    ad.get_similar_artists = AsyncMock(
        return_value=SimilarArtistsResponse(
            similar_artists=[SimilarArtist(musicbrainz_id=_B, name="B")]
        )
    )
    svc = _make_service(
        library_view_service, db, "use-scrobble-targets", artist_discovery=ad, client_factory=cf
    )
    hits = await svc.get_similar_songs(_A, user_id="user-alice")
    assert {t.title for t in hits} == {"A1", "B1"}
    ad.get_similar_artists.assert_awaited_once()


async def test_similar_use_scrobble_targets_no_targets_falls_back_local(
    library_view_service, seeded_library
):
    db, lm, _ids = seeded_library
    await _seed_artist(lm, name="A", mbid=_A, rg="rg-a-aaaaaaaaaaaaaaaaaaaaaaaa", title="A1", recording_mbid="rec-a1")
    await _seed_artist(lm, name="B", mbid=_B, rg="rg-b-bbbbbbbbbbbbbbbbbbbbbbbb", title="B1", recording_mbid="rec-b1")
    cf = AsyncMock()
    cf.resolve_lastfm = AsyncMock(return_value=None)
    cf.resolve_listenbrainz = AsyncMock(return_value=None)
    ad = AsyncMock()
    svc = _make_service(
        library_view_service, db, "use-scrobble-targets", artist_discovery=ad, client_factory=cf
    )
    hits = await svc.get_similar_songs(_A, user_id="user-alice")
    assert {t.title for t in hits} == {"A1"}          # local-only fallback
    ad.get_similar_artists.assert_not_called()


async def test_empty_results_do_not_error(library_view_service, seeded_library):
    db, _lm, _ids = seeded_library
    svc = _make_service(library_view_service, db, "local-only")
    assert await svc.get_top_songs("Nobody", user_id="user-alice") == []
    assert await svc.get_similar_songs(_A, user_id="user-alice") == []
