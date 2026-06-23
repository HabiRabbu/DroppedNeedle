"""T0.4 - FavoritesService: per-user add/remove/list/map round-trip."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_add_is_favorite_remove(favorites_service):
    assert await favorites_service.is_favorite("user-alice", "track", "tr1") is False
    await favorites_service.add("user-alice", "track", "tr1")
    assert await favorites_service.is_favorite("user-alice", "track", "tr1") is True
    await favorites_service.remove("user-alice", "track", "tr1")
    assert await favorites_service.is_favorite("user-alice", "track", "tr1") is False


async def test_add_is_idempotent(favorites_service):
    await favorites_service.add("user-alice", "album", "al1")
    await favorites_service.add("user-alice", "album", "al1")
    rows = await favorites_service.list("user-alice", "album")
    assert len(rows) == 1


async def test_list_is_per_user_and_per_kind(favorites_service):
    await favorites_service.add("user-alice", "track", "tr1")
    await favorites_service.add("user-alice", "artist", "ar1")
    await favorites_service.add("user-bob", "track", "tr2")
    alice_tracks = await favorites_service.list("user-alice", "track")
    assert [i for i, _ in alice_tracks] == ["tr1"]
    bob_tracks = await favorites_service.list("user-bob", "track")
    assert [i for i, _ in bob_tracks] == ["tr2"]
    # kind isolation
    assert [i for i, _ in await favorites_service.list("user-alice", "artist")] == ["ar1"]


async def test_list_returns_created_at_and_most_recent_first(favorites_service):
    await favorites_service.add("user-alice", "track", "tr-old")
    await favorites_service.add("user-alice", "track", "tr-new")
    rows = await favorites_service.list("user-alice", "track")
    ids = [i for i, _ in rows]
    assert ids[0] == "tr-new" and "tr-old" in ids
    assert all(isinstance(ts, float) for _, ts in rows)


async def test_map_for_items_batch(favorites_service):
    await favorites_service.add("user-alice", "track", "tr1")
    await favorites_service.add("user-alice", "track", "tr3")
    mapping = await favorites_service.map_for_items(
        "user-alice", "track", ["tr1", "tr2", "tr3"]
    )
    assert set(mapping.keys()) == {"tr1", "tr3"}
    assert all(isinstance(v, float) for v in mapping.values())


async def test_map_for_items_empty_list(favorites_service):
    assert await favorites_service.map_for_items("user-alice", "track", []) == {}


async def test_invalid_kind_raises(favorites_service):
    with pytest.raises(ValueError):
        await favorites_service.add("user-alice", "playlist", "x")
