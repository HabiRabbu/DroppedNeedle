import hashlib
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from api.v1.schemas.home import GenreArtwork
from infrastructure.cache.memory_cache import InMemoryCache
from services.home.genre_artwork_service import GenreArtworkService


def test_service_constructor_has_no_external_artwork_repository_dependency() -> None:
    assert list(inspect.signature(GenreArtworkService).parameters) == [
        "store",
        "cache",
        "local_artwork",
        "legacy_cache_dir",
    ]


class CandidateStore:
    def __init__(self, payload: dict[str, dict[str, object]]) -> None:
        self.payload = payload
        self.calls = 0

    async def list_genre_artwork_candidates(
        self, genres: list[str]
    ) -> dict[str, dict[str, object]]:
        self.calls += 1
        return {name: self.payload[name] for name in genres if name in self.payload}


def _candidate(
    album_id: str,
    *,
    artist_id: str,
    match_count: int,
    content_key: str | None = None,
    available: bool = True,
) -> dict[str, object]:
    return {
        "album_id": album_id,
        "album_title": f"Album {album_id}",
        "album_artist_name": f"Artist {artist_id}",
        "album_artist_id": artist_id,
        "match_count": match_count,
        "cover_version": 1,
        "content_key": content_key or album_id,
        "available": available,
    }


def _reader() -> AsyncMock:
    async def read(candidate: dict[str, object]):
        if not candidate["available"]:
            return None
        content = str(candidate["content_key"]).encode()
        return content, "image/jpeg", "provider", hashlib.sha1(content).hexdigest()

    reader = AsyncMock()
    reader.read.side_effect = read
    return reader


@pytest.mark.asyncio
async def test_batch_is_one_store_query_and_caches_gradient_absence() -> None:
    store = CandidateStore(
        {
            "Latin": {
                "genre_folded": "latin",
                "revision": 4,
                "candidates": [],
            },
            "Electronic": {
                "genre_folded": "electronic",
                "revision": 2,
                "candidates": [],
            },
        }
    )
    cache = InMemoryCache()
    reader = _reader()
    service = GenreArtworkService(store, cache, reader)

    first = await service.get_artwork_batch(["Latin", "Electronic"])
    second = await service.get_artwork_batch(["Latin", "Electronic"])

    assert store.calls == 2
    assert first == second
    assert all(item.kind == "gradient" for item in first.values())
    assert reader.read.await_count == 0
    assert cache.size() == 2


@pytest.mark.asyncio
async def test_selection_is_local_deterministic_diverse_and_distinct() -> None:
    candidates = [
        _candidate("a", artist_id="same", match_count=10, content_key="shared"),
        _candidate("b", artist_id="same", match_count=10, content_key="shared"),
        _candidate("c", artist_id="other", match_count=10),
        _candidate("d", artist_id="third", match_count=9),
        _candidate("missing", artist_id="fourth", match_count=20, available=False),
        _candidate("unrelated-bach", artist_id="bach", match_count=0),
    ]
    payload = {
        "Latin": {
            "genre_folded": "latin",
            "revision": 7,
            "candidates": candidates[:-1],
        }
    }
    first = await GenreArtworkService(
        CandidateStore(payload), InMemoryCache(), _reader()
    ).get_artwork_batch(["Latin"])
    second = await GenreArtworkService(
        CandidateStore(payload), InMemoryCache(), _reader()
    ).get_artwork_batch(["Latin"])

    selected = first["Latin"].albums
    assert first == second
    assert first["Latin"].kind == "collage"
    assert len(selected) == 3
    assert {album.album_id for album in selected}.isdisjoint(
        {"missing", "unrelated-bach"}
    )
    assert {album.album_id for album in selected[:2]} & {"c"}
    assert len({album.album_id for album in selected} & {"a", "b"}) == 1


@pytest.mark.asyncio
async def test_revision_change_cannot_read_old_cached_payload() -> None:
    cache = InMemoryCache()
    reader = _reader()
    store = CandidateStore(
        {
            "Rock": {
                "genre_folded": "rock",
                "revision": 1,
                "candidates": [_candidate("old", artist_id="one", match_count=1)],
            }
        }
    )
    service = GenreArtworkService(store, cache, reader)
    assert (await service.get_artwork_batch(["Rock"]))["Rock"].albums[
        0
    ].album_id == "old"

    store.payload["Rock"] = {
        "genre_folded": "rock",
        "revision": 2,
        "candidates": [_candidate("new", artist_id="two", match_count=1)],
    }
    changed = await service.get_artwork_batch(["Rock"])

    assert changed["Rock"].albums[0].album_id == "new"
    assert cache.size() == 2


@pytest.mark.asyncio
async def test_cached_album_is_revalidated_when_association_bytes_vanish() -> None:
    candidate = _candidate("album", artist_id="artist", match_count=2)
    store = CandidateStore(
        {
            "Indie": {
                "genre_folded": "indie",
                "revision": 3,
                "candidates": [candidate],
            }
        }
    )
    cache = InMemoryCache()
    reader = _reader()
    service = GenreArtworkService(store, cache, reader)
    assert (await service.get_artwork_batch(["Indie"]))["Indie"].kind == "collage"

    candidate["available"] = False
    changed = await service.get_artwork_batch(["Indie"])

    assert changed["Indie"] == GenreArtwork(
        kind="gradient", version="v2:3:e3b0c44298fc"
    )


@pytest.mark.asyncio
async def test_old_global_artist_payload_is_removed_and_cannot_populate_artwork(
    tmp_path: Path,
) -> None:
    old_cache = tmp_path / "genre_sections"
    old_cache.mkdir()
    payload = old_cache / "listenbrainz.json"
    payload.write_text(
        '{"genre_artists":{"Latin":"bach"},"genre_artist_images":{"Latin":"remote"}}'
    )
    store = CandidateStore(
        {
            "Latin": {
                "genre_folded": "latin",
                "revision": 0,
                "candidates": [],
            }
        }
    )
    service = GenreArtworkService(store, InMemoryCache(), _reader(), old_cache)

    result = await service.get_artwork_batch(["Latin"])

    assert result["Latin"].kind == "gradient"
    assert not payload.exists()
