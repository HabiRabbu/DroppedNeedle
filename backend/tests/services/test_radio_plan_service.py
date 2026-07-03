"""RadioPlanService: seed expansion, pool mixing, fast mode, exclusions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.discover import RadioPlanRequest, RadioSeedItem
from core.exceptions import ValidationError
from services.discover.radio_plan_service import RadioPlanService

_UID = "user-1"


def _svc(**overrides) -> RadioPlanService:
    lb = MagicMock()
    lb.get_similar_artists = AsyncMock(return_value=[])
    lb.get_artist_top_release_groups = AsyncMock(return_value=[])
    lb.get_artist_top_recordings = AsyncMock(return_value=[])
    mb = MagicMock()
    mb.get_release_group = AsyncMock(return_value=None)
    mbid = MagicMock()
    mbid.normalize_mbid = staticmethod(lambda m: m.lower() if m else None)
    library_db = MagicMock()
    library_db.get_files_by_artist_mbids = AsyncMock(return_value=[])
    genre_index = MagicMock()
    genre_index.get_artists_for_genres = AsyncMock(return_value={})
    lfm = MagicMock()
    lfm.get_tag_top_artists = AsyncMock(return_value=[])
    deps = dict(
        lb_repo=lb, mb_repo=mb, mbid_svc=mbid,
        library_db=library_db, genre_index=genre_index, lfm_repo=lfm,
    )
    deps.update(overrides)
    return RadioPlanService(**deps)


def _lib_row(title: str, artist: str, artist_mbid: str, recording: str | None = None):
    return {
        "track_title": title,
        "artist_name": artist,
        "artist_mbid": artist_mbid,
        "album_artist_name": artist,
        "album_artist_mbid": artist_mbid,
        "recording_mbid": recording,
        "release_group_mbid": "rg-x",
        "album_title": "Some Album",
    }


def _recording(title: str, artist: str, recording: str):
    return SimpleNamespace(
        track_name=title, artist_name=artist, recording_mbid=recording, listen_count=10
    )


class TestSeedExpansion:
    @pytest.mark.asyncio
    async def test_artist_seed_expands_to_similar_when_not_fast(self):
        svc = _svc()
        svc._lb_repo.get_similar_artists = AsyncMock(
            return_value=[
                SimpleNamespace(artist_mbid=f"sim-{i}", artist_name=f"Sim {i}", listen_count=1)
                for i in range(10)
            ]
        )
        req = RadioPlanRequest(seed_type="artist", seed_id="seed-1", mode="library")
        await svc.build_plan(_UID, req)
        called_mbids = svc._library_db.get_files_by_artist_mbids.await_args.args[0]
        assert called_mbids[0] == "seed-1"
        assert len(called_mbids) == 8  # seed + 7 similar (capped)

    @pytest.mark.asyncio
    async def test_fast_mode_skips_similar_expansion(self):
        svc = _svc()
        req = RadioPlanRequest(seed_type="artist", seed_id="seed-1", mode="library", fast=True)
        await svc.build_plan(_UID, req)
        svc._lb_repo.get_similar_artists.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_items_seed_uses_given_artists(self):
        svc = _svc()
        req = RadioPlanRequest(
            seed_type="items",
            items=[
                RadioSeedItem(artist_mbid="a-1", artist_name="One"),
                RadioSeedItem(artist_mbid="a-1", artist_name="Dup"),
                RadioSeedItem(artist_mbid="a-2", artist_name="Two"),
            ],
            mode="library",
        )
        await svc.build_plan(_UID, req)
        called_mbids = svc._library_db.get_files_by_artist_mbids.await_args.args[0]
        assert called_mbids == ["a-1", "a-2"]

    @pytest.mark.asyncio
    async def test_genre_seed_uses_library_index_then_lastfm(self):
        svc = _svc()
        svc._genre_index.get_artists_for_genres = AsyncMock(
            return_value={"shoegaze": ["lib-1", "lib-2"]}
        )
        svc._lfm_repo.get_tag_top_artists = AsyncMock(
            return_value=[SimpleNamespace(mbid="tag-1", name="Tag Artist")]
        )
        req = RadioPlanRequest(seed_type="genre", seed_id="shoegaze", mode="library")
        resp = await svc.build_plan(_UID, req)
        assert resp.title == "Radio: Shoegaze"
        called_mbids = svc._library_db.get_files_by_artist_mbids.await_args.args[0]
        assert "tag-1" in called_mbids
        assert any(m.startswith("lib-") for m in called_mbids)

    @pytest.mark.asyncio
    async def test_empty_seed_id_rejected(self):
        svc = _svc()
        with pytest.raises(ValidationError):
            await svc.build_plan(_UID, RadioPlanRequest(seed_type="artist", seed_id="  "))


class TestPoolsAndMixing:
    @pytest.mark.asyncio
    async def test_library_mode_never_calls_external(self):
        svc = _svc()
        svc._library_db.get_files_by_artist_mbids = AsyncMock(
            return_value=[_lib_row(f"T{i}", "A", "a-1") for i in range(5)]
        )
        req = RadioPlanRequest(seed_type="artist", seed_id="a-1", mode="library", fast=True)
        resp = await svc.build_plan(_UID, req)
        assert all(t.in_library for t in resp.tracks)
        svc._lb_repo.get_artist_top_recordings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hybrid_interleaves_library_and_external(self):
        svc = _svc()
        svc._library_db.get_files_by_artist_mbids = AsyncMock(
            return_value=[_lib_row(f"Lib{i}", f"LibArtist{i}", f"la-{i}") for i in range(10)]
        )
        svc._lb_repo.get_artist_top_recordings = AsyncMock(
            return_value=[_recording(f"Ext{i}", f"ExtArtist{i}", f"rec-{i}") for i in range(5)]
        )
        req = RadioPlanRequest(seed_type="artist", seed_id="a-1", mode="hybrid", fast=True, count=10)
        resp = await svc.build_plan(_UID, req)
        assert any(t.in_library for t in resp.tracks)
        assert any(not t.in_library for t in resp.tracks)
        # alternating pools: first two entries come from different pools
        assert resp.tracks[0].in_library != resp.tracks[1].in_library

    @pytest.mark.asyncio
    async def test_per_artist_cap(self):
        svc = _svc()
        svc._library_db.get_files_by_artist_mbids = AsyncMock(
            return_value=[_lib_row(f"T{i}", "Same", "same-1") for i in range(10)]
        )
        req = RadioPlanRequest(seed_type="artist", seed_id="same-1", mode="library", fast=True, count=10)
        resp = await svc.build_plan(_UID, req)
        assert len(resp.tracks) <= 4  # _MAX_PER_ARTIST

    @pytest.mark.asyncio
    async def test_excluded_recordings_are_skipped(self):
        svc = _svc()
        svc._lb_repo.get_artist_top_recordings = AsyncMock(
            return_value=[
                _recording("Played", "A", "rec-played"),
                _recording("New", "A", "rec-new"),
            ]
        )
        req = RadioPlanRequest(
            seed_type="artist",
            seed_id="a-1",
            mode="hybrid",
            fast=True,
            exclude_recording_mbids=["REC-PLAYED"],
        )
        resp = await svc.build_plan(_UID, req)
        names = [t.track_name for t in resp.tracks]
        assert "Played" not in names
        assert "New" in names

    @pytest.mark.asyncio
    async def test_count_is_clamped(self):
        svc = _svc()
        svc._library_db.get_files_by_artist_mbids = AsyncMock(
            return_value=[_lib_row(f"T{i}", f"A{i}", f"a-{i}") for i in range(80)]
        )
        req = RadioPlanRequest(seed_type="artist", seed_id="a-0", mode="library", fast=True, count=500)
        resp = await svc.build_plan(_UID, req)
        assert len(resp.tracks) <= 50


class TestExternalFallbackChain:
    @pytest.mark.asyncio
    async def test_lastfm_covers_lb_popularity_outage(self):
        # LB's popularity API goes down under load (observed live 2026-07-03):
        # the station must still fill from Last.fm
        svc = _svc()
        svc._lb_repo.get_artist_top_recordings = AsyncMock(side_effect=RuntimeError("disabled"))
        svc._lfm_repo.get_artist_top_tracks = AsyncMock(
            return_value=[SimpleNamespace(name="Lucky Man", mbid="rec-lfm")]
        )
        req = RadioPlanRequest(
            seed_type="items",
            items=[RadioSeedItem(artist_mbid="a-1", artist_name="The Verve")],
            mode="hybrid",
        )
        resp = await svc.build_plan(_UID, req)
        assert [t.track_name for t in resp.tracks] == ["Lucky Man"]

    @pytest.mark.asyncio
    async def test_deezer_is_the_last_resort(self):
        svc = _svc()
        svc._lb_repo.get_artist_top_recordings = AsyncMock(side_effect=RuntimeError("disabled"))
        svc._lfm_repo.get_artist_top_tracks = AsyncMock(return_value=[])
        preview_repo = MagicMock()
        preview_repo.get_artist_top_tracks = AsyncMock(
            return_value=[
                SimpleNamespace(title="Bitter Sweet Symphony", artist_name="The Verve")
            ]
        )
        svc._preview_repo = preview_repo
        req = RadioPlanRequest(
            seed_type="items",
            items=[RadioSeedItem(artist_mbid="a-1", artist_name="The Verve")],
            mode="hybrid",
        )
        resp = await svc.build_plan(_UID, req)
        assert [t.track_name for t in resp.tracks] == ["Bitter Sweet Symphony"]
        preview_repo.get_artist_top_tracks.assert_awaited_once_with("The Verve", limit=5)
