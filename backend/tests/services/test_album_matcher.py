"""Tests for AlbumIdentifier — per-folder track-list matching."""

import itertools
import random
from unittest.mock import AsyncMock

import pytest

from models.search import SearchResult
from repositories.musicbrainz_album import RecordingMatch, RecordingReleaseGroup
from services.native.album_matcher import (
    AlbumIdentifier,
    LocalTrack,
    MBTrack,
    _ReleaseMeta,
    _clean,
    _hungarian,
    _string_penalty,
    assign_tracks,
    score_release,
    track_distance,
)

_SANTANA = [
    "Waiting", "Evil Ways", "Shades of Time", "Savor", "Jingo",
    "Persuasion", "Treat", "You Just Don't Care", "Soul Sacrifice",
]


def _locals(titles, *, album="Santana", artist="Santana", duration=240.0):
    return [
        LocalTrack(
            path=f"/m/{i:02d}.flac", title=t, artist=artist, album=album,
            track_number=i + 1, duration_seconds=duration,
        )
        for i, t in enumerate(titles)
    ]


def _mb_tracks(titles, *, disc=1, start_abs=0, length_ms=240000, rec_prefix="rec"):
    out = []
    absolute = start_abs
    for pos, title in enumerate(titles, 1):
        absolute += 1
        out.append(
            MBTrack(
                title=title, position=pos, disc=disc, absolute_position=absolute,
                length_ms=length_ms, recording_mbid=f"{rec_prefix}-{absolute}",
            )
        )
    return out


def test_clean_folds_case_accents_and_drops_punctuation():
    assert _clean("Björk!") == "bjork"
    assert _clean("A.S.A.P  -  Rocky") == "asaprocky"


def test_string_penalty_bounds():
    assert _string_penalty("waiting", "waiting") == 0.0
    assert _string_penalty("", "") == 0.0
    assert _string_penalty("anything", "") == 1.0
    assert _string_penalty("abc", "xyz") == 1.0


def test_track_distance_title_and_duration_grace():
    a = MBTrack(title="Waiting", position=1, disc=1, absolute_position=1, length_ms=240000)
    near = LocalTrack(path="x", title="Waiting", artist="", album="", track_number=1,
                      duration_seconds=247.0)
    assert track_distance(near, a).normalized() == 0.0
    far = LocalTrack(path="x", title="Waiting", artist="", album="", track_number=1,
                     duration_seconds=285.0)
    assert track_distance(far, a).normalized() > 0.0


def test_track_index_accepts_absolute_or_per_disc_number():
    mb = MBTrack(title="X", position=1, disc=2, absolute_position=10, length_ms=None)
    per_disc = LocalTrack(path="x", title="X", artist="", album="", track_number=1)
    absolute = LocalTrack(path="x", title="X", artist="", album="", track_number=10)
    wrong = LocalTrack(path="x", title="X", artist="", album="", track_number=4)
    assert track_distance(per_disc, mb).normalized() == 0.0
    assert track_distance(absolute, mb).normalized() == 0.0
    assert track_distance(wrong, mb).normalized() > 0.0


def test_hungarian_matches_brute_force_optimum():
    rng = random.Random(7)
    for _ in range(200):
        n = rng.randint(1, 6)
        cost = [[rng.random() for _ in range(n)] for _ in range(n)]
        got = sum(cost[i][j] for i, j in enumerate(_hungarian(cost)))
        best = min(
            sum(cost[i][p[i]] for i in range(n))
            for p in itertools.permutations(range(n))
        )
        assert abs(got - best) < 1e-9


def test_assign_tracks_avoids_collisions_and_reports_extras():
    locals_ = [
        LocalTrack(path="a", title="Scream", artist="", album="", track_number=1),
        LocalTrack(path="b", title="Screamm", artist="", album="", track_number=2),
    ]
    mb = [
        MBTrack(title="Scream", position=1, disc=1, absolute_position=1, recording_mbid="r1"),
        MBTrack(title="Screamm", position=2, disc=1, absolute_position=2, recording_mbid="r2"),
        MBTrack(title="Screammm", position=3, disc=1, absolute_position=3, recording_mbid="r3"),
    ]
    mapping, local_extra, mb_extra, _ = assign_tracks(locals_, mb)
    assert mapping == {0: 0, 1: 1}
    assert local_extra == []
    assert mb_extra == [2]


def test_score_release_ranks_standalone_album_above_compilation():
    locals_ = _locals(_SANTANA, album="The Woodstock Experience")
    debut = _mb_tracks(_SANTANA)
    comp = _mb_tracks(_SANTANA, disc=1) + _mb_tracks(
        [f"Live {i}" for i in range(8)], disc=2, start_abs=9, rec_prefix="live"
    )
    m_debut = score_release(
        locals_, debut,
        _ReleaseMeta(release_group_mbid="rg-debut", release_mbid="rel-debut",
                     album_title="Santana", artist="Santana", is_various=False, year=1969),
    )
    m_comp = score_release(
        locals_, comp,
        _ReleaseMeta(release_group_mbid="rg-comp", release_mbid="rel-comp",
                     album_title="The Woodstock Experience", artist="Santana",
                     is_various=False, year=2009),
    )
    assert m_debut.distance < m_comp.distance
    assert m_debut.accepted is True
    assert len(m_debut.assignments) == 9


def test_score_release_rejects_wrong_artist_despite_matching_titles():
    locals_ = _locals(_SANTANA, album="Santana", artist="Santana")
    mb = _mb_tracks(_SANTANA)
    match = score_release(
        locals_, mb,
        _ReleaseMeta(release_group_mbid="rg", release_mbid="rel", album_title="Santana",
                     artist="The Karaoke Crew", is_various=False, year=2010),
    )
    assert match.accepted is False


def test_score_release_accepts_various_artists_release():
    locals_ = _locals(_SANTANA, album="Woodstock", artist="Santana")
    mb = _mb_tracks(_SANTANA)
    match = score_release(
        locals_, mb,
        _ReleaseMeta(release_group_mbid="rg", release_mbid="rel", album_title="Woodstock",
                     artist="Various Artists", is_various=True, year=1994),
    )
    assert match.accepted is True


def test_score_release_rejects_when_few_files_map():
    locals_ = _locals(["Waiting"] + [f"Unrelated {i}" for i in range(4)], album="Mystery")
    mb = _mb_tracks(_SANTANA)
    match = score_release(
        locals_, mb,
        _ReleaseMeta(release_group_mbid="rg", release_mbid="rel", album_title="Santana",
                     artist="Santana", is_various=False, year=1969),
    )
    assert match.accepted is False


def _rg_detail(title, artist, releases):
    return {
        "title": title,
        "artist-credit": [{"name": artist, "artist": {"id": "a1", "name": artist}}],
        "releases": releases,
    }


def _release(rel_id, disc_counts, *, status="Official", date="1969"):
    return {
        "id": rel_id, "status": status, "date": date,
        "media": [{"track-count": c} for c in disc_counts],
    }


def _release_tracks(titles_by_disc):
    media = []
    absolute = 0
    for disc_no, titles in enumerate(titles_by_disc, 1):
        tracks = []
        for pos, title in enumerate(titles, 1):
            absolute += 1
            tracks.append({
                "title": title, "position": pos, "length": 240000,
                "recording": {"id": f"rec-{absolute}", "title": title},
            })
        media.append({"position": disc_no, "tracks": tracks})
    return {"date": "1969", "media": media}


def _santana_repo():
    """Repo where the title search finds only the comp; recording search surfaces the debut."""
    repo = AsyncMock()
    repo.search_albums = AsyncMock(return_value=[
        SearchResult(type="album", title="The Woodstock Experience",
                     musicbrainz_id="rg-comp", artist="Santana"),
    ])
    repo.search_recordings = AsyncMock(return_value=[
        RecordingMatch(
            recording_mbid="rec-x", title="Waiting", artist="Santana", score=100,
            release_groups=[
                RecordingReleaseGroup("rg-debut", "Santana", "rel-debut", "Album", ()),
                RecordingReleaseGroup("rg-comp", "The Woodstock Experience", "rel-comp",
                                      "Album", ("Compilation",)),
            ],
        ),
    ])

    async def rg_detail(mbid, includes=None):
        if mbid == "rg-debut":
            return _rg_detail("Santana", "Santana", [_release("rel-debut", [9])])
        return _rg_detail("The Woodstock Experience", "Santana",
                          [_release("rel-comp", [9, 8], date="2009")])

    async def release(rel_id, includes=None):
        if rel_id == "rel-debut":
            return _release_tracks([_SANTANA])
        return _release_tracks([_SANTANA, [f"Live {i}" for i in range(8)]])

    repo.get_release_group_by_id = AsyncMock(side_effect=rg_detail)
    repo.get_release_by_id = AsyncMock(side_effect=release)
    return repo


@pytest.mark.asyncio
async def test_identify_picks_standalone_release_over_compilation():
    identifier = AlbumIdentifier(_santana_repo())
    locals_ = _locals(_SANTANA, album="The Woodstock Experience")
    match = await identifier.identify(locals_)
    assert match is not None
    assert match.accepted is True
    assert match.release_group_mbid == "rg-debut"
    assert match.release_mbid == "rel-debut"
    assert len(match.assignments) == 9
    assert match.artist_mbid == "a1"
    assert match.artist_name == "Santana"


def test_score_release_omits_artist_for_various_artists():
    locals_ = _locals(_SANTANA, album="Woodstock", artist="Santana")
    mb = _mb_tracks(_SANTANA)
    match = score_release(
        locals_, mb,
        _ReleaseMeta(release_group_mbid="rg", release_mbid="rel", album_title="Woodstock",
                     artist="Various Artists", is_various=True, artist_mbid="va-id"),
    )
    assert match.artist_mbid is None
    assert match.artist_name is None


@pytest.mark.asyncio
async def test_resolve_release_group_artist_returns_primary_credit():
    repo = AsyncMock()
    repo.get_release_group_by_id = AsyncMock(return_value=_rg_detail(
        "?", "XXXTENTACION", [_release("rel", [18])],
    ))
    mbid, name = await AlbumIdentifier(repo).resolve_release_group_artist("rg-1")
    assert name == "XXXTENTACION"
    assert mbid == "a1"
    repo.get_release_group_by_id.assert_awaited_once_with("rg-1", includes=["artist-credits"])


@pytest.mark.asyncio
async def test_resolve_release_group_artist_handles_missing_data():
    repo = AsyncMock()
    repo.get_release_group_by_id = AsyncMock(return_value=None)
    assert await AlbumIdentifier(repo).resolve_release_group_artist("rg-1") == (None, None)
    assert await AlbumIdentifier(repo).resolve_release_group_artist("") == (None, None)


@pytest.mark.asyncio
async def test_identify_returns_none_for_single_file():
    identifier = AlbumIdentifier(_santana_repo())
    assert await identifier.identify(_locals(["Waiting"])) is None


@pytest.mark.asyncio
async def test_identify_returns_none_when_no_candidate_accepts():
    repo = AsyncMock()
    repo.search_albums = AsyncMock(return_value=[])
    repo.search_recordings = AsyncMock(return_value=[])
    identifier = AlbumIdentifier(repo)
    assert await identifier.identify(_locals(_SANTANA)) is None


@pytest.mark.asyncio
async def test_identify_falls_back_when_release_track_counts_missing():
    repo = AsyncMock()
    repo.search_albums = AsyncMock(return_value=[
        SearchResult(type="album", title="Santana", musicbrainz_id="rg-debut", artist="Santana"),
    ])
    repo.search_recordings = AsyncMock(return_value=[])
    repo.get_release_group_by_id = AsyncMock(return_value=_rg_detail(
        "Santana", "Santana", [{"id": "rel-debut", "status": "Official", "media": [{}]}],
    ))
    repo.get_release_by_id = AsyncMock(return_value=_release_tracks([_SANTANA]))
    identifier = AlbumIdentifier(repo)
    match = await identifier.identify(_locals(_SANTANA, album="Santana"))
    assert match is not None and match.release_group_mbid == "rg-debut"
    assert len(match.assignments) == 9
