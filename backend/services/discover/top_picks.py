"""Pure scoring logic for the Top Picks section ("We think you'd like X - 78% match").

Signals (all 0..1):
- ``sim``   - artist similarity to the user's seed artists (LB scores normalised by
              the batch max; Last.fm ``match`` used directly). Trending-pool
              candidates score 0.
- ``genre`` - overlap between the candidate artist's genres and the user's top
              genres: ``|intersection| / 3`` capped at 1.
- ``pop``   - ``min(1, log10(listen_count + 1) / 6)``.

``score = 0.5*sim + 0.35*genre + 0.15*pop`` plus a deterministic per-day jitter
(md5 of user+mbid+date - NEVER random(): determinism keeps the cached list honest
within a day while varying across days). ``match_pct = round(40 + 58*score)`` so we
never claim 100%. Diversity: max one album per artist in the final list.
"""

import hashlib
import math

import msgspec


class TopPickCandidate(msgspec.Struct, kw_only=True):
    release_group_mbid: str
    album_name: str
    artist_name: str
    artist_mbid: str = ""
    sim: float = 0.0
    listen_count: int = 0
    seed_artist: str | None = None
    from_trending: bool = False


class ScoredPick(msgspec.Struct, kw_only=True):
    candidate: TopPickCandidate
    score: float
    match_pct: int
    reasons: list[str]


def _daily_jitter(user_id: str, mbid: str, date_iso: str) -> float:
    digest = hashlib.md5(f"{user_id}:{mbid}:{date_iso}".encode()).hexdigest()
    return (int(digest[:6], 16) % 1000) / 20000  # 0 .. 0.05


def score_candidates(
    candidates: list[TopPickCandidate],
    *,
    user_id: str,
    date_iso: str,
    user_genres: set[str],
    genres_by_artist: dict[str, list[str]],
    count: int = 12,
) -> list[ScoredPick]:
    if not candidates:
        return []

    scored: list[ScoredPick] = []
    for c in candidates:
        candidate_genres = {
            g.lower() for g in genres_by_artist.get(c.artist_mbid.lower(), [])
        }
        genre_overlap = min(1.0, len(candidate_genres & user_genres) / 3)
        pop = min(1.0, math.log10(c.listen_count + 1) / 6)
        score = 0.5 * c.sim + 0.35 * genre_overlap + 0.15 * pop
        score += _daily_jitter(user_id, c.release_group_mbid, date_iso)
        score = min(1.0, score)

        reasons: list[str] = []
        if c.seed_artist and c.sim > 0:
            reasons.append(f"Because you listen to {c.seed_artist}")
        if genre_overlap >= 0.33 and candidate_genres & user_genres:
            top_shared = sorted(candidate_genres & user_genres)[0]
            reasons.append(f"You love {top_shared}")
        if c.from_trending and not reasons:
            reasons.append("Trending worldwide")

        scored.append(
            ScoredPick(
                candidate=c,
                score=score,
                match_pct=round(40 + 58 * score),
                reasons=reasons[:2],
            )
        )

    scored.sort(key=lambda s: s.score, reverse=True)

    # diversity: max one album per artist in the final list
    selected: list[ScoredPick] = []
    seen_artists: set[str] = set()
    seen_mbids: set[str] = set()
    for pick in scored:
        artist_key = pick.candidate.artist_mbid.lower() or pick.candidate.artist_name.lower()
        mbid_key = pick.candidate.release_group_mbid.lower()
        if mbid_key in seen_mbids or artist_key in seen_artists:
            continue
        selected.append(pick)
        seen_artists.add(artist_key)
        seen_mbids.add(mbid_key)
        if len(selected) >= count:
            break
    return selected
