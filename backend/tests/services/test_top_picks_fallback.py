"""Top Picks popularity fallback gate: prefer ListenBrainz ALWAYS, fall back to
Last.fm ONLY when LB's popularity API is DEFINITELY degraded (owner requirement)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from infrastructure.service_health import service_health
from services.discover.homepage_service import DiscoverHomepageService


def _svc() -> DiscoverHomepageService:
    # bypass the heavy DI constructor; set only what the gate/mapper touch
    svc = object.__new__(DiscoverHomepageService)
    svc._lfm_repo = AsyncMock()
    svc._mbid = AsyncMock()
    svc._mbid.normalize_mbid = staticmethod(lambda m: m)
    return svc


@pytest.fixture(autouse=True)
def _clean_health():
    service_health.clear()
    yield
    service_health.clear()


class TestPopularityGate:
    def test_prefers_listenbrainz_when_healthy(self):
        assert _svc()._use_lastfm_for_popularity(lfm_enabled=True) is False

    def test_falls_back_only_when_definitely_degraded(self):
        svc = _svc()
        service_health.mark_degraded(
            "listenbrainz", "popularity", message="down", fallback="lastfm"
        )
        assert svc._use_lastfm_for_popularity(lfm_enabled=True) is True

    def test_never_falls_back_without_lastfm(self):
        svc = _svc()
        service_health.mark_degraded("listenbrainz", "popularity", message="down")
        assert svc._use_lastfm_for_popularity(lfm_enabled=False) is False

    def test_gate_heals_when_signal_stops(self):
        # a single degraded mark with a tiny TTL expires -> back to preferring LB
        svc = _svc()
        service_health.mark_degraded(
            "listenbrainz", "popularity", message="down", ttl_seconds=0
        )
        # ttl_seconds=0 -> already expired on the next check
        assert svc._use_lastfm_for_popularity(lfm_enabled=True) is False


class TestLastfmCandidateMapping:
    @pytest.mark.asyncio
    async def test_candidates_keep_lb_similarity_and_seed(self):
        svc = _svc()
        svc._lfm_repo.get_artist_top_albums = AsyncMock(
            return_value=[SimpleNamespace(name="Album X", artist_name="Sim Artist", mbid="al-1")]
        )
        svc._mbid.lastfm_albums_to_queue_items = AsyncMock(
            return_value=[
                SimpleNamespace(
                    release_group_mbid="rg-1",
                    album_name="Album X",
                    artist_name="Sim Artist",
                    artist_mbid="sim-mbid",
                )
            ]
        )

        sim_artist_list = [("sim-mbid", (0.9, "Sim Artist", "Seed Artist"))]
        candidates: list = []
        await svc._add_lastfm_top_pick_candidates(sim_artist_list, set(), set(), candidates)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.release_group_mbid == "rg-1"
        assert c.sim == 0.9  # LB-derived similarity preserved through the Last.fm mapping
        assert c.seed_artist == "Seed Artist"

    @pytest.mark.asyncio
    async def test_no_candidates_when_lastfm_empty(self):
        svc = _svc()
        svc._lfm_repo.get_artist_top_albums = AsyncMock(return_value=[])
        svc._mbid.lastfm_albums_to_queue_items = AsyncMock(return_value=[])

        candidates: list = []
        await svc._add_lastfm_top_pick_candidates(
            [("m", (0.5, "A", "S"))], set(), set(), candidates
        )
        assert candidates == []
        svc._mbid.lastfm_albums_to_queue_items.assert_not_called()


class TestDailyMixRadioPoolGate:
    """Daily Mixes + Radio shelves turn similar artists into albums via LB popularity;
    the shared pool builder must prefer LB and only use Last.fm when definitely degraded."""

    @pytest.mark.asyncio
    async def test_pools_use_listenbrainz_when_healthy(self, monkeypatch):
        import services.discover.homepage_service as mod

        lb_called = AsyncMock(return_value=[])
        lfm_called = AsyncMock(return_value=[])
        monkeypatch.setattr(mod, "build_similar_artist_pools", lb_called)
        monkeypatch.setattr(mod, "build_similar_artist_pools_lastfm", lfm_called)

        svc = _svc()
        svc._lb_repo = AsyncMock()
        await svc._similar_artist_album_pools(
            ["seed"], ["m"], excluded_mbids=set(), similar_limit=10, albums_per=3, lfm_enabled=True
        )
        lb_called.assert_awaited_once()
        lfm_called.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pools_use_lastfm_only_when_degraded(self, monkeypatch):
        import services.discover.homepage_service as mod

        lb_called = AsyncMock(return_value=[])
        lfm_called = AsyncMock(return_value=[])
        monkeypatch.setattr(mod, "build_similar_artist_pools", lb_called)
        monkeypatch.setattr(mod, "build_similar_artist_pools_lastfm", lfm_called)

        service_health.mark_degraded("listenbrainz", "popularity", message="down")
        svc = _svc()
        svc._lb_repo = AsyncMock()
        await svc._similar_artist_album_pools(
            ["seed"], ["m"], excluded_mbids=set(), similar_limit=10, albums_per=3, lfm_enabled=True
        )
        lfm_called.assert_awaited_once()
        lb_called.assert_not_awaited()
