"""AlbumPreflightScorer tests - the highest-stakes code in Phase 6.

Covers the two-phase scoring, tier assignment (auto/manual/rejected), quarantine
exclusion, the quality floor, CJK preservation, edition-suffix subset matching,
version-mismatch penalty, and the artist-from-path heuristic.

Per the binding rejected-tier-retention design (final pre-implementation review),
below-threshold groups are KEPT in the ranked list tagged ``tier='rejected'`` (so
the Review tab's "Show all results anyway" needs no re-search) rather than
removed - so junk/mixed-source assertions check the tier, not absence.
"""

from unittest.mock import AsyncMock

import pytest
from rapidfuzz import fuzz

from models.download import ScoredCandidate, TargetAlbum
from repositories.protocols.download_client import DownloadSearchResult
from services.native.acquisition.decision import SpecPolicy
from services.native.album_preflight_scorer import (
    AlbumPreflightScorer,
    _artist_from_path,
    _file_confidence,
    _normalize_for_match,
    rank_stored_candidates,
)


def _mk(
    parent,
    name,
    *,
    ext="flac",
    bitrate=900,
    username="alice",
    speed=2_000_000,
    free=True,
    queue_length=0,
):
    return DownloadSearchResult(
        username=username,
        filename=f"{parent}/{name}",
        parent_directory=parent,
        size=30_000_000,
        extension=ext,
        bitrate=bitrate,
        bit_depth=16 if ext == "flac" else None,
        sample_rate=44100,
        duration=240.0,
        has_free_slot=free,
        upload_speed=speed,
        queue_length=queue_length,
    )


def _store(quarantine=None):
    store = AsyncMock()
    store.load_quarantine_set.return_value = set(quarantine or set())
    return store


_TARGET = TargetAlbum(
    artist_name="Radiohead", album_title="OK Computer", year=1997, track_count=12
)
_PARENT = "Radiohead OK Computer 1997"


@pytest.mark.asyncio
async def test_perfect_album_auto_accepted():
    files = [_mk(_PARENT, f"OK Computer {n:02d}.flac") for n in range(1, 13)]
    scorer = AlbumPreflightScorer(_store())
    candidates = await scorer.rank(_TARGET, files)
    assert len(candidates) == 1
    top = candidates[0]
    assert top.coherence == pytest.approx(1.0)
    assert top.final_score >= 0.85
    assert top.tier == "auto"


@pytest.mark.asyncio
async def test_partial_album_is_manual():
    # 7/12 tracks, generic filenames (low title match), no free slot / no speed.
    files = [
        _mk(_PARENT, f"{n:02d} Airbag.mp3", ext="mp3", bitrate=320, speed=0, free=False)
        for n in range(1, 8)
    ]
    scorer = AlbumPreflightScorer(_store())
    candidates = await scorer.rank(_TARGET, files)
    top = candidates[0]
    assert 0.50 <= top.final_score < 0.70
    assert top.tier == "manual"


@pytest.mark.asyncio
async def test_numbered_sequel_folder_rejected_for_self_titled_debut():
    # The Led Zeppelin case on Soulseek: a "Led Zeppelin II" folder must not be picked for
    # a "Led Zeppelin" (debut) request - it's dropped before scoring, not ranked.
    target = TargetAlbum(
        artist_name="Led Zeppelin", album_title="Led Zeppelin", year=1969, track_count=9
    )
    sequel = [
        _mk("Led Zeppelin - Led Zeppelin II (1969)", f"{n:02d} Track.flac")
        for n in range(1, 10)
    ]
    scorer = AlbumPreflightScorer(_store())
    assert await scorer.rank(target, sequel) == []
    # the actual debut folder still scores normally
    debut = [
        _mk("Led Zeppelin - Led Zeppelin (1969)", f"{n:02d} Track.flac")
        for n in range(1, 10)
    ]
    assert len(await scorer.rank(target, debut)) == 1


@pytest.mark.asyncio
async def test_junk_folder_is_rejected():
    files = [
        _mk(
            "Various Artists - Unknown Album",
            "track.mp3",
            ext="mp3",
            bitrate=320,
            username="charlie",
        )
    ]
    scorer = AlbumPreflightScorer(_store())
    candidates = await scorer.rank(_TARGET, files)
    junk = next(c for c in candidates if c.username == "charlie")
    assert junk.coherence < 0.50
    assert junk.tier == "rejected"


@pytest.mark.asyncio
async def test_quarantined_candidate_excluded():
    from models.download_identity import soulseek_identity

    files = [_mk(_PARENT, f"OK Computer {n:02d}.flac") for n in range(1, 13)]
    quarantined = {
        ("soulseek", soulseek_identity(f.username, f.filename)) for f in files
    }
    scorer = AlbumPreflightScorer(_store(quarantine=quarantined))
    candidates = await scorer.rank(_TARGET, files)
    assert all(c.username != "alice" for c in candidates)


@pytest.mark.asyncio
async def test_mixed_sources_split_by_coherence():
    good = [_mk(_PARENT, f"OK Computer {n:02d}.flac") for n in range(1, 13)]
    bad = [
        _mk(
            "Various Artists - Unknown Album",
            "x.mp3",
            ext="mp3",
            bitrate=320,
            username="charlie",
        )
    ]
    scorer = AlbumPreflightScorer(_store())
    candidates = await scorer.rank(_TARGET, good + bad)
    alice = next(c for c in candidates if c.username == "alice")
    charlie = next(c for c in candidates if c.username == "charlie")
    assert alice.tier == "auto"
    assert charlie.tier == "rejected"


@pytest.mark.asyncio
async def test_threshold_configurable():
    files = [
        _mk(_PARENT, f"{n:02d} Airbag.mp3", ext="mp3", bitrate=320, speed=0, free=False)
        for n in range(1, 8)
    ]
    scorer = AlbumPreflightScorer(_store())
    relaxed = await scorer.rank(_TARGET, files, auto_accept_threshold=0.50)
    assert relaxed[0].tier == "auto"


@pytest.mark.asyncio
async def test_quality_gate_drops_out_of_range_keeps_in_range():
    # default range mp3_320..lossless: a 96kbps mp3 (tier 'low') is dropped; FLAC kept.
    low_mp3 = _mk(_PARENT, "01 Airbag.mp3", ext="mp3", bitrate=96, username="bob")
    # FLAC with EMPTY extension field and ABSENT bitrate - still classed lossless (C6a/C6b).
    lossless = DownloadSearchResult(
        username="alice",
        filename=f"{_PARENT}/OK Computer 01.flac",
        parent_directory=_PARENT,
        size=30_000_000,
        extension="",
        bitrate=None,
    )
    scorer = AlbumPreflightScorer(
        _store()
    )  # defaults: mp3_320..lossless, flac_mp3_only
    candidates = await scorer.rank(_TARGET, [low_mp3, lossless])
    all_files = [f for c in candidates for f in c.files]
    assert all(
        f.username != "bob" for f in all_files
    )  # 96kbps mp3 out of range -> dropped
    assert any(f.username == "alice" for f in all_files)  # lossless kept


@pytest.mark.asyncio
async def test_folder_with_sidecars_still_matches_and_enqueues_audio_only():
    # A real Soulseek folder search returns the album's sidecars (cover art, cue, log,
    # m3u) alongside the FLACs. They must not gate the folder out (codec/quality) nor be
    # enqueued as tracks - the regression behind "no matching candidate" on 173 results.
    audio = [_mk(_PARENT, f"OK Computer {n:02d}.flac") for n in range(1, 13)]
    sidecars = [
        _mk(_PARENT, "cover.jpg", ext="jpg", bitrate=None),
        _mk(_PARENT, "folder.png", ext="png", bitrate=None),
        _mk(_PARENT, "OK Computer.cue", ext="cue", bitrate=None),
        _mk(_PARENT, "OK Computer.log", ext="log", bitrate=None),
        _mk(_PARENT, "00.m3u", ext="m3u", bitrate=None),
    ]
    scorer = AlbumPreflightScorer(
        _store()
    )  # defaults: flac_mp3_only, mp3_320..lossless
    candidates = await scorer.rank(_TARGET, audio + sidecars)
    assert len(candidates) == 1
    top = candidates[0]
    assert top.tier == "auto"
    assert top.coherence == pytest.approx(
        1.0
    )  # 12/12 audio, sidecars don't inflate the count
    # only the FLACs are enqueued; no sidecar would reach (and fail) the importer
    assert all(f.filename.endswith(".flac") for f in top.files)
    assert len(top.files) == 12


@pytest.mark.asyncio
async def test_art_only_folder_is_not_a_candidate():
    # A folder of pure cover art (no audio) must not become a candidate.
    art = [
        _mk(
            "Radiohead OK Computer Scans",
            "front.jpg",
            ext="jpg",
            bitrate=None,
            username="bob",
        ),
        _mk(
            "Radiohead OK Computer Scans",
            "back.jpg",
            ext="jpg",
            bitrate=None,
            username="bob",
        ),
    ]
    scorer = AlbumPreflightScorer(_store())
    candidates = await scorer.rank(_TARGET, art)
    assert candidates == []


@pytest.mark.asyncio
async def test_flac_mp3_only_excludes_other_codecs():
    flac = _mk(_PARENT, "01.flac", ext="flac")
    ogg = _mk(f"{_PARENT} (ogg)", "01.ogg", ext="ogg", bitrate=320, username="bob")
    scorer = AlbumPreflightScorer(_store())  # flac_mp3_only=True (default)
    users = {c.username for c in await scorer.rank(_TARGET, [flac, ogg])}
    assert "bob" not in users  # OGG folder excluded by flac_mp3_only
    assert "alice" in users
    # toggle off -> the 320 OGG folder is now allowed
    scorer_any = AlbumPreflightScorer(_store(), flac_mp3_only=False)
    assert "bob" in {c.username for c in await scorer_any.rank(_TARGET, [flac, ogg])}


@pytest.mark.asyncio
async def test_only_lossless_range_drops_mp3():
    flac = [_mk(_PARENT, f"{n:02d}.flac", ext="flac") for n in range(1, 13)]
    mp3 = [
        _mk(f"{_PARENT} (mp3)", f"{n:02d}.mp3", ext="mp3", bitrate=320, username="bob")
        for n in range(1, 13)
    ]
    scorer = AlbumPreflightScorer(
        _store(), quality_min="lossless", quality_max="lossless"
    )
    users = {c.username for c in await scorer.rank(_TARGET, flac + mp3)}
    assert "bob" not in users  # MP3 dropped: only lossless accepted
    assert "alice" in users


@pytest.mark.asyncio
async def test_match_band_precedes_quality_tier():
    # A weak FLAC must not hide a materially better MP3 match. Quality remains the
    # preference only after candidates are in the same safe identity band.
    mp3 = [
        _mk(_PARENT, f"OK Computer {n:02d}.mp3", ext="mp3", bitrate=320)
        for n in range(1, 13)
    ]
    flac = [
        _mk("Radiohead OK Computer", f"{n:02d}.flac", ext="flac", username="bob")
        for n in range(1, 13)
    ]
    scorer = AlbumPreflightScorer(_store())
    candidates = await scorer.rank(_TARGET, mp3 + flac)
    assert candidates[0].username == "alice"


@pytest.mark.asyncio
async def test_auto_candidate_precedes_non_auto_hires_candidate():
    non_auto_hires = [
        DownloadSearchResult(
            username="hires-but-wrong",
            filename="Music/Radiohead/OK Computer Deluxe/01 stray.flac",
            parent_directory="OK Computer Deluxe",
            size=80_000_000,
            extension="flac",
            bitrate=900,
            bit_depth=24,
            sample_rate=96000,
            duration=240.0,
            has_free_slot=True,
            upload_speed=20_000_000,
            queue_length=0,
        )
    ]
    safe_redbook = [
        _mk(_PARENT, f"OK Computer {n:02d}.flac", username="safe") for n in range(1, 13)
    ]

    candidates = await AlbumPreflightScorer(_store()).rank(
        _TARGET, non_auto_hires + safe_redbook
    )

    assert candidates[0].username == "safe"
    assert candidates[0].tier == "auto"
    assert candidates[-1].username == "hires-but-wrong"
    assert candidates[-1].tier != "auto"


@pytest.mark.asyncio
async def test_same_match_band_prefers_free_slot_then_shorter_queue_then_speed():
    def peer(username, *, free, queue_length, speed):
        return [
            _mk(
                _PARENT,
                f"OK Computer {n:02d}.flac",
                username=username,
                free=free,
                queue_length=queue_length,
                speed=speed,
            )
            for n in range(1, 13)
        ]

    results = [
        *peer("long-fast", free=False, queue_length=5, speed=20_000_000),
        *peer("short-slow", free=False, queue_length=1, speed=1_000_000),
        *peer("short-fast", free=False, queue_length=1, speed=5_000_000),
        *peer("free-slow", free=True, queue_length=0, speed=500_000),
    ]

    candidates = await AlbumPreflightScorer(_store()).rank(_TARGET, results)

    assert [candidate.username for candidate in candidates] == [
        "free-slow",
        "short-fast",
        "short-slow",
        "long-fast",
    ]


@pytest.mark.asyncio
async def test_avalon_does_not_accept_so_long_avalon():
    target = TargetAlbum(
        artist_name="Anthony Green", album_title="Avalon", year=2008, track_count=12
    )
    wrong_album = [
        _mk(
            "[2025] So Long, Avalon",
            f"Music/Anthony Green/[2025] So Long, Avalon/{n:02d} track.flac",
            username="wrong-album",
        )
        for n in range(1, 13)
    ]
    avalon = [
        _mk(
            "[2008] Avalon",
            f"Music/Anthony Green/[2008] Avalon/{n:02d} track.flac",
            username="correct-album",
        )
        for n in range(1, 13)
    ]

    candidates = await AlbumPreflightScorer(_store()).rank(target, wrong_album + avalon)

    assert [candidate.username for candidate in candidates] == ["correct-album"]


def test_stored_review_is_safely_reranked_without_losing_pick_indexes():
    target = TargetAlbum(
        artist_name="Anthony Green", album_title="Avalon", year=2008, track_count=12
    )
    manual = ScoredCandidate(
        username="manual",
        parent_directory="Avalon Deluxe",
        files=[
            _mk(
                "Avalon Deluxe",
                "Music/Anthony Green/Avalon Deluxe/01 track.flac",
                username="manual",
            )
        ],
        final_score=0.59,
        tier="manual",
    )
    wrong = ScoredCandidate(
        username="wrong",
        parent_directory="[2025] So Long, Avalon",
        files=[
            _mk(
                "[2025] So Long, Avalon",
                "Music/Anthony Green/[2025] So Long, Avalon/01 track.flac",
                username="wrong",
            )
        ],
        final_score=0.90,
        tier="auto",
    )
    safe = ScoredCandidate(
        username="safe",
        parent_directory="[2008] Avalon",
        files=[
            _mk(
                "[2008] Avalon",
                "Music/Anthony Green/[2008] Avalon/01 track.flac",
                username="safe",
            )
        ],
        final_score=0.85,
        tier="auto",
    )

    projected = rank_stored_candidates(target, [manual, wrong, safe])

    assert [candidate.username for candidate in projected] == ["safe", "manual"]
    assert [candidate.candidate_index for candidate in projected] == [2, 0]


@pytest.mark.asyncio
async def test_hires_folder_outranks_redbook_within_lossless():
    # H1: a 24/96 FLAC folder must rank ABOVE a 16/44 FLAC folder of the same album (same
    # tier), where before the captured bit_depth/sample_rate were never read by the sort.
    redbook = [
        _mk(_PARENT, f"OK Computer {n:02d}.flac") for n in range(1, 13)
    ]  # 16/44100
    hires = [
        DownloadSearchResult(
            username="bob",
            filename=f"{_PARENT}/OK Computer {n:02d}.flac",
            parent_directory=_PARENT,
            size=80_000_000,
            extension="flac",
            bitrate=900,
            bit_depth=24,
            sample_rate=96000,
            duration=240.0,
        )
        for n in range(1, 13)
    ]
    scorer = AlbumPreflightScorer(_store())
    candidates = await scorer.rank(_TARGET, redbook + hires)
    assert (
        candidates[0].username == "bob"
    )  # the 24/96 folder ranks first within lossless
    assert candidates[0].files[0].bit_depth == 24


def test_cjk_not_mangled():
    text = "林宥嘉 神秘嘉宾"
    assert _normalize_for_match(text) == text.lower()
    assert fuzz.token_set_ratio(text, "林宥嘉 - 神秘嘉宾 - 01") >= 85


def test_edition_suffix_subset_match():
    score = fuzz.token_set_ratio(
        _normalize_for_match("OK Computer"),
        _normalize_for_match("OK Computer OKNOTOK 1997-2017"),
    )
    assert score >= 85


def test_artist_from_path_variants():
    assert _artist_from_path("Radiohead - OK Computer") == "Radiohead"
    assert _artist_from_path("Artist/Album") == "Artist"
    assert _artist_from_path("", "Fallback") == ""


@pytest.mark.asyncio
async def test_obfuscated_live_folder_rejected_via_shared_edition_spec():
    # ArrRebuild M3: the Soulseek path now runs the shared wrong_edition spec. A folder the
    # wrong-album guard DEFERS on (no readable artist, Q4) is still dropped when it carries
    # an edition marker the studio request never asked for - previously it survived as a
    # rejected-tier candidate.
    target = TargetAlbum(
        artist_name="Radiohead", album_title="OK Computer", track_count=12
    )
    live = [
        _mk("Live at Glastonbury 2003 xq-scrambled", f"{n:02d}.flac")
        for n in range(1, 13)
    ]
    scorer = AlbumPreflightScorer(_store())
    assert await scorer.rank(target, live) == []


@pytest.mark.asyncio
async def test_ignored_term_policy_drops_folder():
    # A user ignored-term drops a folder that the always-on guards would have kept.
    files = [_mk(f"{_PARENT} WEB", f"OK Computer {n:02d}.flac") for n in range(1, 13)]
    scorer = AlbumPreflightScorer(
        _store(),
        policy=SpecPolicy(
            quality_min="mp3_320", quality_max="lossless", ignored_terms=("web",)
        ),
    )
    assert await scorer.rank(_TARGET, files) == []
    # without the policy it scores normally
    assert len(await AlbumPreflightScorer(_store()).rank(_TARGET, files)) == 1


@pytest.mark.asyncio
async def test_max_size_policy_drops_oversize_folder():
    # 12 * 30MB = 360MB; a 100MB cap rejects the whole folder (a mislabeled boxset).
    files = [_mk(_PARENT, f"OK Computer {n:02d}.flac") for n in range(1, 13)]
    scorer = AlbumPreflightScorer(_store(), policy=SpecPolicy(max_size_mb=100))
    assert await scorer.rank(_TARGET, files) == []


def test_version_mismatch_penalised():
    remix = DownloadSearchResult(
        username="u",
        filename="x/Song (Remix).flac",
        parent_directory="Artist - Album",
        size=1,
        extension="flac",
    )
    original = DownloadSearchResult(
        username="u",
        filename="x/Song.flac",
        parent_directory="Artist - Album",
        size=1,
        extension="flac",
    )
    conf_remix = _file_confidence("Song", "Artist", None, remix)
    conf_original = _file_confidence("Song", "Artist", None, original)
    assert conf_remix < conf_original
    assert conf_remix < 0.70  # off-version cannot auto-accept
