"""NewReleaseService: baseline detection, fan-out enqueue, and graceful
degradation (Phase 4)."""

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.exceptions import ConfigurationError, ExternalServiceError
from infrastructure.persistence.follow_store import FollowStore
from services.native.download_service import ALREADY_IN_LIBRARY
from services.native.new_release_service import NewReleaseService
from tests.helpers import make_builtin_dispatcher

ARTIST = "AAAAAAAA-1111-2222-3333-444444444444"
ARTIST_LOWER = ARTIST.lower()


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users "
            "(id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user')"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, display_name, role) VALUES (?, ?, ?)",
            [("user-a", "Alice", "user"), ("user-b", "Bob", "user"), ("admin-1", "Admin", "admin")],
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS library_files "
            "(id TEXT PRIMARY KEY, release_group_mbid TEXT, deleted_at REAL)"
        )
        conn.commit()
    finally:
        conn.close()


def _rg(mbid: str, title: str, *, primary="Album", secondary=None, date="2020-01-01"):
    d = {"id": mbid, "title": title, "primary-type": primary, "first-release-date": date}
    if secondary is not None:
        d["secondary-types"] = secondary
    return d


@pytest.fixture
def svc(tmp_path: Path):
    db = tmp_path / "library.db"
    store = FollowStore(db_path=db, write_lock=threading.Lock())
    _seed_auth_users(db)

    mb = AsyncMock()
    mb.get_artist_release_groups_or_raise = AsyncMock(return_value=([], 0))
    downloads = AsyncMock()
    downloads.request_album = AsyncMock(return_value="task-1")
    download_store = AsyncMock()
    download_store.get_active_task_for_album_any_user = AsyncMock(return_value=None)
    library = AsyncMock()
    library.get_library_mbids = AsyncMock(return_value=set())
    sse = AsyncMock()

    service = NewReleaseService(
        follow_store=store,
        mb_repo=mb,
        acquisition=make_builtin_dispatcher(lambda: downloads),
        download_store=download_store,
        library_repo=library,
        sse_publisher=sse,
        inter_artist_delay=0.0,
    )
    return SimpleNamespace(
        service=service, store=store, mb=mb, downloads=downloads,
        download_store=download_store, library=library, sse=sse, db=db,
    )


async def _follow_with_auto(store, user_id, *, state="approved"):
    await store.follow_artist(user_id, ARTIST, "Radiohead")
    await store.set_auto_download_intent(user_id, ARTIST, True)
    if state:
        await store.upsert_approval(user_id, ARTIST, "Radiohead", state)


@pytest.mark.asyncio
async def test_first_poll_seeds_baseline_and_enqueues_nothing(svc):
    await _follow_with_auto(svc.store, "user-a")
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old 1"), _rg("RG2", "Old 2")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.baselined == 1
    assert summary.new_releases == 0
    svc.downloads.request_album.assert_not_called()
    assert await svc.store.has_cursor(ARTIST_LOWER) is True
    assert await svc.store.known_release_set(ARTIST_LOWER) == {"rg1", "rg2"}
    items, total = await svc.store.list_new_releases_for_user("user-a", 50, 0)
    assert total == 0


@pytest.mark.asyncio
async def test_second_poll_detects_and_enqueues_for_approved(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "Brand New")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.new_releases == 1
    assert summary.enqueued == 1
    svc.downloads.request_album.assert_awaited_once()
    kwargs = svc.downloads.request_album.await_args.kwargs
    assert kwargs["user_id"] == "user-a"
    assert kwargs["release_group_mbid"] == "RG2"
    svc.sse.publish.assert_awaited_once()
    items, total = await svc.store.list_new_releases_for_user("user-a", 50, 0)
    assert total == 1 and items[0].release_group_mbid == "RG2"


@pytest.mark.asyncio
async def test_owned_release_group_is_excluded(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.library.get_library_mbids.return_value = {"rg2"}  # already owned
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "Owned New")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.new_releases == 0
    svc.downloads.request_album.assert_not_called()


@pytest.mark.asyncio
async def test_future_dated_release_is_feed_only(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "Upcoming", date="2099-01-01")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.new_releases == 1
    assert summary.enqueued == 0
    svc.downloads.request_album.assert_not_called()
    # in Wanted...
    _items, total = await svc.store.list_new_releases_for_user("user-a", 50, 0)
    assert total == 1
    # ...but NOT marked known, so a later (released) poll can still enqueue it
    assert "rg2" not in await svc.store.known_release_set(ARTIST_LOWER)


@pytest.mark.asyncio
async def test_noisy_secondary_type_is_filtered(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "Live Album", secondary=["Live"])],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.new_releases == 0
    svc.downloads.request_album.assert_not_called()


@pytest.mark.asyncio
async def test_pending_follower_gets_feed_but_no_enqueue(svc):
    await _follow_with_auto(svc.store, "user-a", state="pending")  # not yet approved
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "New")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.new_releases == 1
    assert summary.enqueued == 0
    svc.downloads.request_album.assert_not_called()
    _items, total = await svc.store.list_new_releases_for_user("user-a", 50, 0)
    assert total == 1  # still in Wanted


@pytest.mark.asyncio
async def test_two_followers_enqueue_once(svc):
    await _follow_with_auto(svc.store, "user-a")
    await _follow_with_auto(svc.store, "user-b")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "New")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.enqueued == 1
    svc.downloads.request_album.assert_awaited_once()  # DD5: one task across followers
    assert svc.downloads.request_album.await_args.kwargs["user_id"] == "user-a"  # deterministic


@pytest.mark.asyncio
async def test_active_task_any_user_blocks_enqueue(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.download_store.get_active_task_for_album_any_user.return_value = object()  # in flight
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "New")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.new_releases == 1
    assert summary.enqueued == 0
    svc.downloads.request_album.assert_not_called()


@pytest.mark.asyncio
async def test_already_in_library_sentinel_skips_sse(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.downloads.request_album.return_value = ALREADY_IN_LIBRARY
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "New")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.enqueued == 0
    svc.sse.publish.assert_not_called()


@pytest.mark.asyncio
async def test_config_error_does_not_crash(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1"])
    svc.downloads.request_album.side_effect = ConfigurationError("download client disabled")
    svc.mb.get_artist_release_groups_or_raise.return_value = (
        [_rg("RG1", "Old"), _rg("RG2", "New")],
        2,
    )
    summary = await svc.service.run_poll()
    assert summary.new_releases == 1
    assert summary.enqueued == 0  # feed populated, but no task created


@pytest.mark.asyncio
async def test_mb_error_does_not_advance_baseline(svc):
    await _follow_with_auto(svc.store, "user-a")
    svc.mb.get_artist_release_groups_or_raise.side_effect = ExternalServiceError("MB down")
    summary = await svc.service.run_poll()
    assert summary.errors == 1
    assert summary.baselined == 0
    # no cursor created -> the next run still baselines (never treats back-catalog as new)
    assert await svc.store.has_cursor(ARTIST_LOWER) is False


@pytest.mark.asyncio
async def test_mb_error_after_baseline_preserves_known_set(svc):
    await _follow_with_auto(svc.store, "user-a")
    await svc.store.seed_baseline(ARTIST_LOWER, ["rg1", "rg2"])
    svc.mb.get_artist_release_groups_or_raise.side_effect = ExternalServiceError("MB down")
    summary = await svc.service.run_poll()
    assert summary.errors == 1
    assert await svc.store.known_release_set(ARTIST_LOWER) == {"rg1", "rg2"}  # unchanged
