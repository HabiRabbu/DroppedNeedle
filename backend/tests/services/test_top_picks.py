"""Top Picks: pure scoring (services/discover/top_picks.py) and the section
builders added alongside it (listeners-like-you, anniversaries, new-from-followed)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.discover import TopPicksSection
from services.discover.homepage_service import DiscoverHomepageService
from services.discover.top_picks import TopPickCandidate, score_candidates

_UID = "user-1"
_DATE = "2026-07-03"


def make_candidate(**overrides) -> TopPickCandidate:
    defaults = dict(
        release_group_mbid="rg-1",
        album_name="Album",
        artist_name="Artist",
        artist_mbid="artist-1",
        sim=0.0,
        listen_count=0,
        seed_artist=None,
        from_trending=False,
    )
    defaults.update(overrides)
    return TopPickCandidate(**defaults)


class TestScoreCandidates:
    def test_match_pct_bounds(self):
        low = make_candidate(release_group_mbid="rg-low")
        high = make_candidate(
            release_group_mbid="rg-high",
            artist_mbid="artist-2",
            sim=1.0,
            listen_count=10_000_000,
            seed_artist="Seed",
        )
        picks = score_candidates(
            [low, high],
            user_id=_UID,
            date_iso=_DATE,
            user_genres={"rock"},
            genres_by_artist={"artist-2": ["rock", "indie"]},
        )
        assert all(40 <= p.match_pct <= 98 for p in picks)
        by_mbid = {p.candidate.release_group_mbid: p for p in picks}
        assert by_mbid["rg-high"].match_pct > by_mbid["rg-low"].match_pct

    def test_deterministic_within_a_day_varies_across_days(self):
        candidates = [make_candidate(release_group_mbid=f"rg-{i}", artist_mbid=f"a-{i}") for i in range(8)]
        kwargs = dict(user_id=_UID, user_genres=set(), genres_by_artist={})
        day1a = score_candidates(list(candidates), date_iso="2026-07-03", **kwargs)
        day1b = score_candidates(list(candidates), date_iso="2026-07-03", **kwargs)
        day2 = score_candidates(list(candidates), date_iso="2026-07-04", **kwargs)
        assert [p.candidate.release_group_mbid for p in day1a] == [
            p.candidate.release_group_mbid for p in day1b
        ]
        assert [p.score for p in day1a] != [p.score for p in day2]

    def test_max_one_album_per_artist(self):
        candidates = [
            make_candidate(release_group_mbid=f"rg-{i}", artist_mbid="same-artist", sim=0.9)
            for i in range(4)
        ] + [make_candidate(release_group_mbid="rg-other", artist_mbid="other", sim=0.5)]
        picks = score_candidates(
            candidates, user_id=_UID, date_iso=_DATE, user_genres=set(), genres_by_artist={}
        )
        artists = [p.candidate.artist_mbid for p in picks]
        assert artists.count("same-artist") == 1
        assert "other" in artists

    def test_reasons_reflect_signals(self):
        seed_pick = make_candidate(
            release_group_mbid="rg-a", artist_mbid="a-1", sim=0.8, seed_artist="Radiohead"
        )
        genre_pick = make_candidate(release_group_mbid="rg-b", artist_mbid="a-2")
        trending_pick = make_candidate(
            release_group_mbid="rg-c", artist_mbid="a-3", from_trending=True
        )
        picks = score_candidates(
            [seed_pick, genre_pick, trending_pick],
            user_id=_UID,
            date_iso=_DATE,
            user_genres={"shoegaze", "dream pop"},
            genres_by_artist={"a-2": ["shoegaze", "noise"]},
        )
        by_mbid = {p.candidate.release_group_mbid: p for p in picks}
        assert by_mbid["rg-a"].reasons[0] == "Because you listen to Radiohead"
        assert by_mbid["rg-b"].reasons == ["You love shoegaze"]
        assert by_mbid["rg-c"].reasons == ["Trending worldwide"]

    def test_count_caps_output(self):
        candidates = [
            make_candidate(release_group_mbid=f"rg-{i}", artist_mbid=f"a-{i}") for i in range(30)
        ]
        picks = score_candidates(
            candidates, user_id=_UID, date_iso=_DATE, user_genres=set(), genres_by_artist={},
            count=5,
        )
        assert len(picks) == 5

    def test_empty_input(self):
        assert score_candidates(
            [], user_id=_UID, date_iso=_DATE, user_genres=set(), genres_by_artist={}
        ) == []


def _svc() -> DiscoverHomepageService:
    svc = DiscoverHomepageService.__new__(DiscoverHomepageService)
    svc._memory_cache = None
    svc._mbid_store = None
    svc._genre_index = None
    svc._library_db = None
    svc._follow_service = None
    svc._integration = MagicMock()
    svc._integration.is_library_configured.return_value = True
    svc._integration.get_discover_picks_settings.return_value = (0.7, 12)
    svc._mbid = MagicMock()
    svc._mbid.normalize_mbid = staticmethod(lambda m: m.lower() if m else None)
    svc._mbid.get_library_album_mbids = AsyncMock(return_value=set())
    svc._mbid.get_user_listened_release_group_mbids = AsyncMock(return_value=set())
    svc._lb_repo = MagicMock()
    svc._lb_repo.get_sitewide_top_release_groups = AsyncMock(return_value=[])
    svc._lb_repo.get_artist_top_release_groups = AsyncMock(return_value=[])
    return svc


def _rg(mbid: str, name: str = "Album", artist: str = "Artist", artist_mbids=None, listens=100):
    return SimpleNamespace(
        release_group_mbid=mbid,
        release_group_name=name,
        artist_name=artist,
        artist_mbids=artist_mbids or ["a-1"],
        listen_count=listens,
    )


class TestBuildTopPicks:
    @pytest.mark.asyncio
    async def test_builds_from_similar_pools_with_seed_reason(self):
        svc = _svc()
        seed = SimpleNamespace(artist_name="Radiohead", artist_mbids=["seed-1"], listen_count=10)
        results = {
            "similar_0": [
                SimpleNamespace(artist_mbid="sim-1", artist_name="The Verve", listen_count=5, score=100.0)
            ]
        }
        svc._lb_repo.get_artist_top_release_groups = AsyncMock(
            return_value=[_rg("rg-1", "Urban Hymns", "The Verve", ["sim-1"])]
        )

        section = await svc._build_top_picks(_UID, "listenbrainz", True, "u", results, [seed])

        assert isinstance(section, TopPicksSection)
        assert section.items
        item = section.items[0]
        assert item.album.mbid == "rg-1"
        assert item.seed_artist == "Radiohead"
        assert 40 <= item.match_pct <= 98
        assert "Because you listen to Radiohead" in item.reasons

    @pytest.mark.asyncio
    async def test_excludes_library_listened_and_ignored(self):
        svc = _svc()
        svc._mbid.get_library_album_mbids = AsyncMock(return_value={"rg-lib"})
        svc._mbid.get_user_listened_release_group_mbids = AsyncMock(return_value={"rg-heard"})
        svc._lb_repo.get_sitewide_top_release_groups = AsyncMock(
            return_value=[
                _rg("rg-lib"),
                _rg("rg-heard", artist_mbids=["a-2"]),
                _rg("rg-new", artist_mbids=["a-3"]),
            ]
        )

        section = await svc._build_top_picks(_UID, "listenbrainz", True, "u", {}, [])

        assert section is not None
        mbids = [i.album.mbid for i in section.items]
        assert mbids == ["rg-new"]

    @pytest.mark.asyncio
    async def test_returns_none_when_no_candidates(self):
        svc = _svc()
        section = await svc._build_top_picks(_UID, "listenbrainz", True, "u", {}, [])
        assert section is None

    @pytest.mark.asyncio
    async def test_result_is_cached(self):
        svc = _svc()
        store: dict = {}
        cache = MagicMock()
        cache.get = AsyncMock(side_effect=lambda k: store.get(k))
        cache.set = AsyncMock(side_effect=lambda k, v, ttl=None: store.__setitem__(k, v))
        svc._memory_cache = cache
        svc._lb_repo.get_sitewide_top_release_groups = AsyncMock(
            return_value=[_rg("rg-new", artist_mbids=["a-3"])]
        )

        first = await svc._build_top_picks(_UID, "listenbrainz", True, "u", {}, [])
        svc._lb_repo.get_sitewide_top_release_groups = AsyncMock(
            side_effect=AssertionError("must hit the cache")
        )
        second = await svc._build_top_picks(_UID, "listenbrainz", True, "u", {}, [])

        assert first is not None
        assert second == first


class TestListenersLikeYou:
    @pytest.mark.asyncio
    async def test_builds_from_similar_users(self):
        svc = _svc()
        lb_client = MagicMock()
        lb_client.get_similar_users = AsyncMock(
            return_value=[{"user_name": "twin", "similarity": 0.9}]
        )
        lb_client.get_user_top_release_groups = AsyncMock(
            return_value=[_rg("rg-t", "Their Album", "Their Artist", ["a-9"])]
        )

        section = await svc._build_listeners_like_you(lb_client, "me", _UID)

        assert section is not None
        assert section.title == "Listeners Like You Are Playing"
        assert section.items[0].mbid == "rg-t"
        lb_client.get_user_top_release_groups.assert_awaited_once_with(
            username="twin", range_="this_month", count=15
        )

    @pytest.mark.asyncio
    async def test_none_when_no_similar_users(self):
        svc = _svc()
        lb_client = MagicMock()
        lb_client.get_similar_users = AsyncMock(return_value=[])
        assert await svc._build_listeners_like_you(lb_client, "me", _UID) is None

    @pytest.mark.asyncio
    async def test_failure_degrades_to_none(self):
        svc = _svc()
        lb_client = MagicMock()
        lb_client.get_similar_users = AsyncMock(side_effect=RuntimeError("lb down"))
        assert await svc._build_listeners_like_you(lb_client, "me", _UID) is None


class TestAnniversaries:
    @pytest.mark.asyncio
    async def test_round_birthdays_only_roundest_first(self):
        from datetime import datetime, timezone

        this_year = datetime.now(timezone.utc).year
        svc = _svc()
        svc._library_db = MagicMock()
        svc._library_db.get_albums = AsyncMock(
            return_value=[
                {"mbid": "rg-30", "title": "Thirty", "artist_name": "A", "year": this_year - 30},
                {"mbid": "rg-10", "title": "Ten", "artist_name": "B", "year": this_year - 10},
                {"mbid": "rg-7", "title": "Seven", "artist_name": "C", "year": this_year - 7},
                {"mbid": "rg-none", "title": "NoYear", "artist_name": "D", "year": None},
            ]
        )

        section = await svc._build_anniversaries()

        assert section is not None
        assert [i.mbid for i in section.items] == ["rg-30", "rg-10"]
        assert all(i.in_library for i in section.items)

    @pytest.mark.asyncio
    async def test_none_without_library_db_or_matches(self):
        svc = _svc()
        assert await svc._build_anniversaries() is None
        svc._library_db = MagicMock()
        svc._library_db.get_albums = AsyncMock(return_value=[])
        assert await svc._build_anniversaries() is None


class TestNewFromFollowed:
    @pytest.mark.asyncio
    async def test_builds_section_from_follow_service(self):
        svc = _svc()
        svc._follow_service = MagicMock()
        svc._follow_service.list_new_releases = AsyncMock(
            return_value=(
                [
                    SimpleNamespace(
                        release_group_mbid="rg-f",
                        title="Fresh",
                        artist_name="Followed",
                        artist_mbid="a-f",
                        primary_type="Album",
                        first_release_date="2026-06-20",
                    )
                ],
                1,
            )
        )

        section = await svc._build_new_from_followed(_UID)

        assert section is not None
        assert section.title == "New From Artists You Follow"
        assert section.items[0].mbid == "rg-f"
        svc._follow_service.list_new_releases.assert_awaited_once_with(_UID, 10, 0)

    @pytest.mark.asyncio
    async def test_none_when_following_nothing(self):
        svc = _svc()
        svc._follow_service = MagicMock()
        svc._follow_service.list_new_releases = AsyncMock(return_value=([], 0))
        assert await svc._build_new_from_followed(_UID) is None
