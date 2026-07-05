"""AuthStore schema idempotency + spotify_oauth_states roundtrip.

The Spotify OAuth flow (PR #108) added the ``spotify_oauth_states`` table inside
``AuthStore._ensure_tables``; per the house rule every new store/migration gets an
idempotency test (construct twice on the same path).
"""

import threading
from pathlib import Path

import pytest

from infrastructure.persistence.auth_store import AuthStore


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    AuthStore(db_path, write_lock=lock)
    # Second construction re-runs _ensure_tables (all CREATE TABLE IF NOT EXISTS +
    # guarded ALTERs); it must not raise.
    AuthStore(db_path, write_lock=lock)
    assert db_path.exists()


@pytest.mark.asyncio
async def test_spotify_state_roundtrip_is_single_use(tmp_path: Path):
    store = AuthStore(tmp_path / "auth.db")
    await store.store_spotify_state("state-abc", "user-1")

    assert await store.consume_spotify_state("state-abc") == "user-1"
    # Single-use: the state is deleted on consume, so a replay yields nothing.
    assert await store.consume_spotify_state("state-abc") is None


@pytest.mark.asyncio
async def test_spotify_state_unknown_returns_none(tmp_path: Path):
    store = AuthStore(tmp_path / "auth.db")
    assert await store.consume_spotify_state("never-stored") is None
