import threading

import pytest

from infrastructure.persistence.user_section_prefs_store import UserSectionPrefsStore


@pytest.fixture
def store(tmp_path):
    return UserSectionPrefsStore(
        db_path=tmp_path / "library.db", write_lock=threading.Lock()
    )


class TestSchemaIdempotency:
    def test_double_construction_on_same_path(self, tmp_path):
        lock = threading.Lock()
        path = tmp_path / "library.db"
        UserSectionPrefsStore(db_path=path, write_lock=lock)
        # second construction must not raise (CREATE TABLE IF NOT EXISTS)
        UserSectionPrefsStore(db_path=path, write_lock=lock)


class TestDisabledSetRoundTrip:
    @pytest.mark.asyncio
    async def test_default_is_all_enabled(self, store):
        assert await store.get_disabled("u1", "home") == set()

    @pytest.mark.asyncio
    async def test_set_and_get_disabled(self, store):
        await store.set_disabled("u1", "discover", {"daily_mixes", "genre_list"})
        assert await store.get_disabled("u1", "discover") == {"daily_mixes", "genre_list"}

    @pytest.mark.asyncio
    async def test_save_replaces_previous_set(self, store):
        await store.set_disabled("u1", "home", {"trending_artists", "popular_albums"})
        await store.set_disabled("u1", "home", {"genre_list"})
        assert await store.get_disabled("u1", "home") == {"genre_list"}

    @pytest.mark.asyncio
    async def test_empty_set_clears_everything(self, store):
        await store.set_disabled("u1", "home", {"trending_artists"})
        await store.set_disabled("u1", "home", set())
        assert await store.get_disabled("u1", "home") == set()

    @pytest.mark.asyncio
    async def test_pages_are_independent(self, store):
        await store.set_disabled("u1", "home", {"trending_artists"})
        await store.set_disabled("u1", "discover", {"daily_mixes"})
        assert await store.get_disabled("u1", "home") == {"trending_artists"}
        assert await store.get_disabled("u1", "discover") == {"daily_mixes"}

    @pytest.mark.asyncio
    async def test_users_are_isolated(self, store):
        await store.set_disabled("u1", "home", {"trending_artists"})
        assert await store.get_disabled("u2", "home") == set()

    @pytest.mark.asyncio
    async def test_unknown_keys_survive_and_are_harmless(self, store):
        # keys from removed sections stay in the DB and are simply ignored by
        # the catalog filter; the store itself round-trips them faithfully
        await store.set_disabled("u1", "home", {"long_gone_section"})
        assert await store.get_disabled("u1", "home") == {"long_gone_section"}
