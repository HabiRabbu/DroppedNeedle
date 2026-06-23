"""Tests for MusicBrainzMatcher (Tier 2) - mocks MusicBrainzRepository (AUD-13)."""

from unittest.mock import AsyncMock

import pytest

from models.search import SearchResult
from repositories.musicbrainz_album import RecordingMatch, RecordingReleaseGroup
from services.native.musicbrainz_matcher import MusicBrainzMatcher, TargetAlbum


def _repo(results: list[SearchResult]) -> AsyncMock:
    repo = AsyncMock()
    repo.search_albums = AsyncMock(return_value=results)
    return repo


def _rg(
    title: str,
    mbid: str,
    primary: str = "Album",
    secondary: tuple[str, ...] = (),
    release: str = "rel-1",
) -> RecordingReleaseGroup:
    return RecordingReleaseGroup(
        release_group_mbid=mbid,
        release_group_title=title,
        release_mbid=release,
        primary_type=primary,
        secondary_types=tuple(secondary),
    )


def _rec(
    title: str,
    mbid: str,
    artist: str,
    groups: list[RecordingReleaseGroup],
    score: int = 100,
) -> RecordingMatch:
    return RecordingMatch(
        recording_mbid=mbid, title=title, artist=artist, score=score, release_groups=groups
    )


def _repo2(albums: list[SearchResult], recordings: list[RecordingMatch]) -> AsyncMock:
    repo = AsyncMock()
    repo.search_albums = AsyncMock(return_value=albums)
    repo.search_recordings = AsyncMock(return_value=recordings)
    return repo


def _result(title: str, mbid: str = "rg-1", artist: str = "Radiohead") -> SearchResult:
    return SearchResult(type="album", title=title, musicbrainz_id=mbid, artist=artist, year=1997)


@pytest.mark.asyncio
async def test_text_match_auto_accepts_good_match():
    matcher = MusicBrainzMatcher(_repo([_result("OK Computer", "rg-ok")]))
    res = await matcher.text_match(TargetAlbum(artist="Radiohead", album="OK Computer"))
    assert res.confidence >= 0.85
    assert res.release_group_mbid == "rg-ok"
    assert res.matched is True


@pytest.mark.asyncio
async def test_text_match_strips_edition_before_matching():
    matcher = MusicBrainzMatcher(_repo([_result("OK Computer (Deluxe Edition)", "rg-deluxe")]))
    res = await matcher.text_match(TargetAlbum(artist="Radiohead", album="OK Computer"))
    assert res.confidence >= 0.85
    assert res.release_group_mbid == "rg-deluxe"


@pytest.mark.asyncio
async def test_text_match_folds_diacritics():
    # Tag "Bjork / Homogenic" (ASCII) matches the accented MB result via unidecode.
    matcher = MusicBrainzMatcher(_repo([_result("Homogénic", "rg-bjork", artist="Björk")]))
    res = await matcher.text_match(TargetAlbum(artist="Bjork", album="Homogenic"))
    assert res.confidence >= 0.85
    assert res.release_group_mbid == "rg-bjork"


@pytest.mark.asyncio
async def test_text_match_cjk_not_transliterated():
    matcher = MusicBrainzMatcher(_repo([_result("神秘嘉宾 (Deluxe)", "rg-cjk", artist="林宥嘉")]))
    res = await matcher.text_match(TargetAlbum(artist="林宥嘉", album="神秘嘉宾"))
    assert res.confidence >= 0.85
    assert res.release_group_mbid == "rg-cjk"


@pytest.mark.asyncio
async def test_text_match_picks_best_of_several():
    matcher = MusicBrainzMatcher(
        _repo([_result("Kid A", "rg-kida"), _result("OK Computer", "rg-ok")])
    )
    res = await matcher.text_match(TargetAlbum(artist="Radiohead", album="OK Computer"))
    assert res.release_group_mbid == "rg-ok"


@pytest.mark.asyncio
async def test_text_match_no_results_is_unmatched():
    matcher = MusicBrainzMatcher(_repo([]))
    res = await matcher.text_match(TargetAlbum(artist="Nobody", album="Nothing"))
    assert res.confidence == 0.0
    assert res.release_group_mbid is None
    assert res.matched is False


@pytest.mark.asyncio
async def test_text_match_below_threshold_returns_no_mbid():
    matcher = MusicBrainzMatcher(_repo([_result("Completely Different Album", "rg-x")]))
    res = await matcher.text_match(TargetAlbum(artist="Radiohead", album="OK Computer"))
    assert res.release_group_mbid is None
    assert res.matched is False


@pytest.mark.asyncio
async def test_wrong_artist_same_title_is_rejected():
    # Same album title by a completely different artist must not auto-accept.
    matcher = MusicBrainzMatcher(_repo([_result("Greatest Hits", "rg-wrong", artist="Queen")]))
    res = await matcher.text_match(TargetAlbum(artist="ABBA", album="Greatest Hits"))
    assert res.release_group_mbid is None
    assert res.matched is False


@pytest.mark.asyncio
async def test_artist_named_like_edition_word_not_rejected():
    # The band "Live" must survive the artist gate - the raw ratio (no edition
    # stripping) is why; stripping "live" would zero the artist out.
    matcher = MusicBrainzMatcher(_repo([_result("Throwing Copper", "rg-live", artist="Live")]))
    res = await matcher.text_match(TargetAlbum(artist="Live", album="Throwing Copper"))
    assert res.release_group_mbid == "rg-live"


@pytest.mark.asyncio
async def test_text_match_artist_case_insensitive():
    matcher = MusicBrainzMatcher(
        _repo([_result("Electra Heart", "rg-eh", artist="Marina and the Diamonds")])
    )
    res = await matcher.text_match(TargetAlbum(artist="MARINA", album="Electra Heart"))
    assert res.release_group_mbid == "rg-eh"
    assert res.matched is True


@pytest.mark.asyncio
async def test_text_match_multi_artist_credit():
    matcher = MusicBrainzMatcher(
        _repo([_result("Give Me My Flowers", "rg-flowers", artist="Blu & Exile")])
    )
    res = await matcher.text_match(
        TargetAlbum(artist="blu; Exile; Fashawn; Johaz", album="Give Me My Flowers")
    )
    assert res.release_group_mbid == "rg-flowers"


@pytest.mark.asyncio
async def test_text_match_remaster_edition_and_case():
    matcher = MusicBrainzMatcher(
        _repo([_result("Black and Blue", "rg-bb", artist="The Rolling Stones")])
    )
    res = await matcher.text_match(
        TargetAlbum(artist="The Rolling Stones", album="Black And Blue (Remastered 2009)")
    )
    assert res.release_group_mbid == "rg-bb"


@pytest.mark.asyncio
async def test_text_match_symbol_only_title_does_not_false_match():
    matcher = MusicBrainzMatcher(
        _repo([_result("Some Other Album", "rg-other", artist="XXXTENTACION")])
    )
    res = await matcher.text_match(TargetAlbum(artist="XXXTENTACION", album="?"))
    assert res.release_group_mbid is None
    assert res.matched is False


def test_title_similarity_is_case_insensitive():
    assert MusicBrainzMatcher.title_similarity("Music To Scream To", "Music to Scream To") >= 0.99


def test_title_similarity_empty_after_normalise_is_zero():
    assert MusicBrainzMatcher.title_similarity("?", "?") == 0.0


@pytest.mark.asyncio
async def test_matcher_only_uses_repo_for_mb_access():
    repo = _repo([_result("OK Computer", "rg-ok")])
    matcher = MusicBrainzMatcher(repo)
    await matcher.text_match(TargetAlbum(artist="Radiohead", album="OK Computer"))
    repo.search_albums.assert_awaited_once()  # no raw HTTP - only the repo


# -- Tier 3: recording MBID -> release-group MBID (AUD-13: via the repo) --


@pytest.mark.asyncio
async def test_resolve_recording_returns_release_group():
    repo = AsyncMock()
    repo.resolve_recording_to_release_group = AsyncMock(return_value="rg-xyz")
    matcher = MusicBrainzMatcher(repo)
    assert await matcher.resolve_recording_to_release_group("rec-1") == "rg-xyz"
    repo.resolve_recording_to_release_group.assert_awaited_once_with("rec-1")


@pytest.mark.asyncio
async def test_resolve_recording_none_when_no_release_group():
    repo = AsyncMock()
    repo.resolve_recording_to_release_group = AsyncMock(return_value=None)
    matcher = MusicBrainzMatcher(repo)
    assert await matcher.resolve_recording_to_release_group("rec-1") is None


@pytest.mark.asyncio
async def test_resolve_recording_empty_id_short_circuits():
    repo = AsyncMock()
    repo.resolve_recording_to_release_group = AsyncMock()
    matcher = MusicBrainzMatcher(repo)
    assert await matcher.resolve_recording_to_release_group("") is None
    repo.resolve_recording_to_release_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_recording_fails_open_on_repo_error():
    repo = AsyncMock()
    repo.resolve_recording_to_release_group = AsyncMock(side_effect=RuntimeError("MB down"))
    matcher = MusicBrainzMatcher(repo)
    assert await matcher.resolve_recording_to_release_group("rec-1") is None


@pytest.mark.asyncio
async def test_resolve_recording_only_uses_repo_for_mb_access():
    repo = AsyncMock()
    repo.resolve_recording_to_release_group = AsyncMock(return_value="rg-1")
    matcher = MusicBrainzMatcher(repo)
    await matcher.resolve_recording_to_release_group("rec-1")
    repo.resolve_recording_to_release_group.assert_awaited_once()  # no raw HTTP


@pytest.mark.asyncio
async def test_album_search_includes_all_secondary_types():
    repo = _repo([_result("Music to Scream To", "rg-poppy", artist="Poppy")])
    matcher = MusicBrainzMatcher(repo)
    res = await matcher.text_match(TargetAlbum(artist="Poppy", album="Music to Scream To"))
    assert res.release_group_mbid == "rg-poppy"
    assert res.matched is True
    assert repo.search_albums.await_args.kwargs.get("include_all_types") is True


@pytest.mark.asyncio
async def test_exact_edition_wins_tie_over_generic_title():
    matcher = MusicBrainzMatcher(_repo([
        _result("Heathens", "rg-generic", artist="Twenty One Pilots"),
        _result("Heathens (DISTO Remix)", "rg-disto", artist="Twenty One Pilots"),
    ]))
    res = await matcher.text_match(
        TargetAlbum(artist="Twenty One Pilots", album="Heathens (DISTO Remix)")
    )
    assert res.release_group_mbid == "rg-disto"
    assert res.matched is True


@pytest.mark.asyncio
async def test_recording_fallback_recovers_title_variant_album():
    albums = [_result("Éthiopiques 21: Piano Solo", "rg-piano", artist="Emahoy")]
    recordings = [
        _rec(
            "The Homeless Wanderer",
            "rec-hw",
            "Emahoy",
            [
                _rg("Éthiopiques 21: Piano Solo", "rg-piano", secondary=("Compilation",)),
                _rg("The Rough Guide to Ethiopian Jazz", "rg-rough", secondary=("Compilation",)),
            ],
        )
    ]
    matcher = MusicBrainzMatcher(_repo2(albums, recordings))
    res = await matcher.text_match(
        TargetAlbum(
            artist="Emahoy",
            album="Éthiopiques 21: Ethiopia Song",
            track_title="The Homeless Wanderer",
            track_number=1,
        )
    )
    assert res.matched is True
    assert res.release_group_mbid == "rg-piano"
    assert res.recording_mbid == "rec-hw"


@pytest.mark.asyncio
async def test_recording_fallback_symbol_only_album_prefers_studio_release():
    recordings = [
        _rec(
            "SAD!",
            "rec-sad",
            "XXXTENTACION",
            [
                _rg("?", "rg-q", primary="Album", secondary=()),
                _rg("Mega Hits 2018", "rg-mega", primary="Album", secondary=("Compilation",)),
            ],
        )
    ]
    matcher = MusicBrainzMatcher(_repo2([], recordings))
    res = await matcher.text_match(
        TargetAlbum(artist="XXXTENTACION", album="?", track_title="SAD!", track_number=1)
    )
    assert res.matched is True
    assert res.release_group_mbid == "rg-q"
    assert res.recording_mbid == "rec-sad"


@pytest.mark.asyncio
async def test_recording_fallback_respects_artist_floor():
    recordings = [_rec("SAD!", "rec-x", "Some Other Artist", [_rg("Whatever", "rg-w")])]
    matcher = MusicBrainzMatcher(_repo2([], recordings))
    res = await matcher.text_match(
        TargetAlbum(artist="XXXTENTACION", album="?", track_title="SAD!")
    )
    assert res.matched is False
    assert res.release_group_mbid is None


@pytest.mark.asyncio
async def test_recording_fallback_requires_recording_title_to_match():
    recordings = [_rec("A Totally Different Song", "rec-d", "Artist", [_rg("Album", "rg-a")])]
    matcher = MusicBrainzMatcher(_repo2([], recordings))
    res = await matcher.text_match(
        TargetAlbum(artist="Artist", album="Some Album", track_title="My Track")
    )
    assert res.matched is False


@pytest.mark.asyncio
async def test_album_match_short_circuits_recording_search():
    repo = _repo2(
        [_result("OK Computer", "rg-ok")],
        [_rec("Airbag", "rec-air", "Radiohead", [_rg("OK Computer", "rg-ok")])],
    )
    matcher = MusicBrainzMatcher(repo)
    res = await matcher.text_match(
        TargetAlbum(artist="Radiohead", album="OK Computer", track_title="Airbag")
    )
    assert res.release_group_mbid == "rg-ok"
    repo.search_recordings.assert_not_awaited()


@pytest.mark.asyncio
async def test_recording_fallback_skipped_without_track_title():
    repo = _repo2([_result("Wrong Album", "rg-w")], [_rec("X", "r", "A", [_rg("Y", "rg-y")])])
    matcher = MusicBrainzMatcher(repo)
    res = await matcher.text_match(TargetAlbum(artist="Radiohead", album="OK Computer"))
    assert res.matched is False
    repo.search_recordings.assert_not_awaited()


def test_select_release_group_prefers_title_then_rank():
    matcher = MusicBrainzMatcher(AsyncMock())
    by_title = matcher._select_release_group(
        "Piano Solo", [_rg("Piano Solo", "a"), _rg("Something Else", "b")]
    )
    assert by_title.release_group_mbid == "a"
    by_rank = matcher._select_release_group(
        "", [_rg("Comp", "c", secondary=("Compilation",)), _rg("Studio", "d")]
    )
    assert by_rank.release_group_mbid == "d"
