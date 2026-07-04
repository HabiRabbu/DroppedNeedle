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

    # Personalised (similar-artist) picks always rank ahead of generic worldwide-trending
    # ones: trending is only the fallback tail that fills the list when we're short on
    # personalised candidates (during the LB-popularity outage these lack a listen-count
    # popularity term, so a plain score sort would let high-play trending outrank them and
    # dilute Top Picks). Relevance order (score) is preserved WITHIN each tier.
    scored.sort(key=lambda s: (s.candidate.from_trending, -s.score))

    # diversity: at most two albums per artist in the final list. One keeps variety; allowing
    # a second (personalised) album beats padding the list with generic worldwide-trending when
    # a heard-heavy library leaves few distinct similar artists with unheard albums.
    selected: list[ScoredPick] = []
    artist_counts: dict[str, int] = {}
    seen_mbids: set[str] = set()
    for pick in scored:
        artist_key = pick.candidate.artist_mbid.lower() or pick.candidate.artist_name.lower()
        mbid_key = pick.candidate.release_group_mbid.lower()
        if mbid_key in seen_mbids or artist_counts.get(artist_key, 0) >= 2:
            continue
        selected.append(pick)
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        seen_mbids.add(mbid_key)
        if len(selected) >= count:
            break
    return selected
