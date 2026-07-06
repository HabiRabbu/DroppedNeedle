"""FollowStore tests (Follow + auto-download feature, Phase 1)."""

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.follow_store import FollowStore, NewReleaseInput


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users "
            "(id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user')"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO auth_users (id, display_name, role) VALUES (?, ?, ?)",
            [
                ("admin-1", "Admin", "admin"),
                ("user-a", "Alice", "user"),
                ("user-b", "Bob", "user"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _seed_library_files(db_path: Path, owned_rg_mbids: list[str]) -> None:
    """Minimal library_files table so the Wanted read's owned-exclusion works."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS library_files "
            "(id TEXT PRIMARY KEY, release_group_mbid TEXT, deleted_at REAL)"
        )
        conn.executemany(
            "INSERT INTO library_files (id, release_group_mbid, deleted_at) VALUES (?, ?, NULL)",
            [(f"f-{i}", mbid.lower()) for i, mbid in enumerate(owned_rg_mbids)],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def store(tmp_path: Path) -> FollowStore:
    db_path = tmp_path / "library.db"
    s = FollowStore(db_path=db_path, write_lock=threading.Lock())
    _seed_auth_users(db_path)
    return s


def _ri(rg: str, artist_lower: str, title: str, **kw) -> NewReleaseInput:
    return NewReleaseInput(
        release_group_mbid=rg,
        release_group_mbid_lower=rg.lower(),
        artist_mbid_lower=artist_lower,
        artist_name=kw.get("artist_name", "Artist"),
        title=title,
        primary_type=kw.get("primary_type", "Album"),
        secondary_types=kw.get("secondary_types"),
        first_release_date=kw.get("first_release_date"),
    )


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    FollowStore(db_path=db_path, write_lock=lock)
    FollowStore(db_path=db_path, write_lock=lock)
    assert db_path.exists()


@pytest.mark.asyncio
async def test_follow_then_state(store: FollowStore):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    state = await store.get_follow_state("user-a", "mbid-a")  # case-insensitive
    assert state.followed is True
    assert state.auto_download is False
    assert state.auto_download_state == "none"


@pytest.mark.asyncio
async def test_unknown_follow_is_not_followed(store: FollowStore):
    state = await store.get_follow_state("user-a", "nope")
    assert state.followed is False
    assert state.auto_download is False
    assert state.auto_download_state == "none"


@pytest.mark.asyncio
async def test_unfollow_returns_bool_and_removes(store: FollowStore):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    assert await store.unfollow_artist("user-a", "mbid-a") is True
    assert await store.unfollow_artist("user-a", "mbid-a") is False
    assert (await store.get_follow_state("user-a", "MBID-A")).followed is False


@pytest.mark.asyncio
async def test_refollow_preserves_intent(store: FollowStore):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.set_auto_download_intent("user-a", "MBID-A", True)
    await store.follow_artist("user-a", "MBID-A", "Radiohead (renamed)")
    state = await store.get_follow_state("user-a", "MBID-A")
    assert state.auto_download is True  # intent survived the re-follow upsert


@pytest.mark.asyncio
async def test_intent_toggle_reflected(store: FollowStore):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.set_auto_download_intent("user-a", "MBID-A", True)
    assert (await store.get_follow_state("user-a", "MBID-A")).auto_download is True
    await store.set_auto_download_intent("user-a", "MBID-A", False)
    assert (await store.get_follow_state("user-a", "MBID-A")).auto_download is False


@pytest.mark.asyncio
async def test_list_followed_artists_scoped_and_ordered(store: FollowStore):
    await store.follow_artist("user-a", "MBID-1", "First")
    await store.follow_artist("user-a", "MBID-2", "Second")
    await store.follow_artist("user-b", "MBID-3", "Other")
    listed = await store.list_followed_artists("user-a")
    assert [a.artist_name for a in listed] == ["Second", "First"]  # followed_at DESC
    assert [a.artist_name for a in await store.list_followed_artists("user-b")] == ["Other"]


@pytest.mark.asyncio
async def test_pending_then_approved_state(store: FollowStore):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.set_auto_download_intent("user-a", "MBID-A", True)
    await store.upsert_approval("user-a", "MBID-A", "Radiohead", "pending")
    assert (await store.get_follow_state("user-a", "MBID-A")).auto_download_state == "pending"

    updated = await store.set_approval_state("user-a", "MBID-A", "approved", ("admin-1", "Admin"))
    assert updated is True
    state = await store.get_follow_state("user-a", "MBID-A")
    assert state.auto_download is True
    assert state.auto_download_state == "approved"

    approval = await store.get_approval("user-a", "MBID-A")
    assert approval is not None
    assert approval.state == "approved"
    assert approval.reviewed_by_id == "admin-1"
    assert approval.reviewed_by_name == "Admin"
    assert approval.reviewed_at is not None


@pytest.mark.asyncio
async def test_reject_then_intent_off_surfaces_hint(store: FollowStore):
    """After a reject (service flips intent 0), the state still surfaces
    'rejected' so the UI can show the declined hint while the follow stays."""
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.set_auto_download_intent("user-a", "MBID-A", True)
    await store.upsert_approval("user-a", "MBID-A", "Radiohead", "pending")
    await store.set_approval_state("user-a", "MBID-A", "rejected", ("admin-1", "Admin"))
    await store.set_auto_download_intent("user-a", "MBID-A", False)
    state = await store.get_follow_state("user-a", "MBID-A")
    assert state.followed is True
    assert state.auto_download is False
    assert state.auto_download_state == "rejected"


@pytest.mark.asyncio
async def test_get_approval_absent_returns_none(store: FollowStore):
    assert await store.get_approval("user-a", "MBID-A") is None


@pytest.mark.asyncio
async def test_set_approval_state_missing_row_returns_false(store: FollowStore):
    assert await store.set_approval_state("user-a", "MBID-A", "approved", ("admin-1", "Admin")) is False


@pytest.mark.asyncio
async def test_upsert_approval_clears_stale_reviewer_on_requeue(store: FollowStore):
    await store.upsert_approval("user-a", "MBID-A", "Radiohead", "pending")
    await store.set_approval_state("user-a", "MBID-A", "rejected", ("admin-1", "Admin"))
    # user re-enables -> fresh pending, reviewer cleared
    await store.upsert_approval("user-a", "MBID-A", "Radiohead", "pending")
    approval = await store.get_approval("user-a", "MBID-A")
    assert approval is not None
    assert approval.state == "pending"
    assert approval.reviewed_by_id is None
    assert approval.reviewed_at is None


@pytest.mark.asyncio
async def test_list_pending_approvals_ordered_with_user_name(store: FollowStore):
    await store.upsert_approval("user-b", "MBID-2", "Beta", "pending")
    await store.upsert_approval("user-a", "MBID-1", "Alpha", "pending")
    await store.upsert_approval("user-a", "MBID-3", "Gamma", "approved")  # not pending
    pending = await store.list_pending_approvals()
    assert len(pending) == 2
    # ordered by requested_at ASC (user-b requested first)
    assert pending[0].user_id == "user-b"
    assert pending[0].user_name == "Bob"
    assert pending[1].user_id == "user-a"
    assert pending[1].user_name == "Alice"


@pytest.mark.asyncio
async def test_distinct_followed_artists_dedups(store: FollowStore):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.follow_artist("user-b", "mbid-a", "Radiohead")  # same artist, diff case
    await store.follow_artist("user-a", "MBID-B", "Bjork")
    distinct = await store.list_distinct_followed_artists()
    assert len(distinct) == 2
    lowers = {d.artist_mbid_lower for d in distinct}
    assert lowers == {"mbid-a", "mbid-b"}


@pytest.mark.asyncio
async def test_baseline_seed_and_known_set(store: FollowStore):
    assert await store.has_cursor("mbid-a") is False
    await store.seed_baseline("mbid-a", ["rg1", "rg2"])
    assert await store.has_cursor("mbid-a") is True
    assert await store.known_release_set("mbid-a") == {"rg1", "rg2"}


@pytest.mark.asyncio
async def test_update_cursor_is_update_only(store: FollowStore):
    """A transient error before the first baseline must NOT create a cursor row,
    or the next poll would treat the entire back-catalog as new (DD2)."""
    await store.update_cursor("mbid-a", "error", "boom")
    assert await store.has_cursor("mbid-a") is False
    # after a real baseline, update_cursor updates the existing row
    await store.seed_baseline("mbid-a", ["rg1"])
    await store.update_cursor("mbid-a", "error", "boom")
    assert await store.has_cursor("mbid-a") is True


@pytest.mark.asyncio
async def test_record_new_releases_is_idempotent(store: FollowStore, tmp_path: Path):
    _seed_library_files(tmp_path / "library.db", owned_rg_mbids=[])
    await store.seed_baseline("mbid-a", ["rg1"])
    rows = [_ri("RG2", "mbid-a", "New Album", first_release_date="2026-01-01")]
    await store.record_new_releases("mbid-a", rows, ["rg2"])
    await store.record_new_releases("mbid-a", rows, ["rg2"])  # INSERT OR IGNORE -> no dup
    assert "rg2" in await store.known_release_set("mbid-a")
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    items, total = await store.list_new_releases_for_user("user-a", 50, 0)
    assert total == 1
    assert items[0].release_group_mbid == "RG2"
    assert items[0].title == "New Album"


@pytest.mark.asyncio
async def test_auto_download_followers_gate(store: FollowStore):
    # admin: intent on, no approval row -> granted by role (DD3)
    await store.follow_artist("admin-1", "MBID-A", "Radiohead")
    await store.set_auto_download_intent("admin-1", "MBID-A", True)
    # user-a: intent on + approved -> granted
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.set_auto_download_intent("user-a", "MBID-A", True)
    await store.upsert_approval("user-a", "MBID-A", "Radiohead", "approved")
    # user-b: intent on + only pending -> excluded
    await store.follow_artist("user-b", "MBID-A", "Radiohead")
    await store.set_auto_download_intent("user-b", "MBID-A", True)
    await store.upsert_approval("user-b", "MBID-A", "Radiohead", "pending")

    followers = await store.list_auto_download_followers("mbid-a")
    assert followers == ["admin-1", "user-a"]  # ordered by user_id, pending excluded


@pytest.mark.asyncio
async def test_auto_download_followers_excludes_intent_off(store: FollowStore):
    await store.follow_artist("admin-1", "MBID-A", "Radiohead")  # intent off
    assert await store.list_auto_download_followers("mbid-a") == []


@pytest.mark.asyncio
async def test_wanted_excludes_owned_and_is_scoped(store: FollowStore, tmp_path: Path):
    _seed_library_files(tmp_path / "library.db", owned_rg_mbids=["RG-OWNED"])
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.follow_artist("user-b", "MBID-B", "Bjork")
    await store.seed_baseline("mbid-a", [])
    await store.seed_baseline("mbid-b", [])
    await store.record_new_releases(
        "mbid-a",
        [
            _ri("RG-NEW", "mbid-a", "Wanted", first_release_date="2026-02-01"),
            _ri("RG-OWNED", "mbid-a", "Already Owned", first_release_date="2026-01-01"),
        ],
        ["rg-new", "rg-owned"],
    )
    await store.record_new_releases(
        "mbid-b",
        [_ri("RG-OTHER", "mbid-b", "Bjork New", first_release_date="2026-03-01")],
        ["rg-other"],
    )

    items, total = await store.list_new_releases_for_user("user-a", 50, 0)
    assert total == 1  # owned excluded, user-b's release not visible
    assert items[0].release_group_mbid == "RG-NEW"
    assert items[0].artist_mbid == "MBID-A"  # original-case from the follow JOIN

    items_b, total_b = await store.list_new_releases_for_user("user-b", 50, 0)
    assert total_b == 1
    assert items_b[0].release_group_mbid == "RG-OTHER"


@pytest.mark.asyncio
async def test_wanted_pagination_newest_first(store: FollowStore, tmp_path: Path):
    _seed_library_files(tmp_path / "library.db", owned_rg_mbids=[])
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.seed_baseline("mbid-a", [])
    await store.record_new_releases(
        "mbid-a",
        [
            _ri("RG-OLD", "mbid-a", "Old", first_release_date="2024-01-01"),
            _ri("RG-MID", "mbid-a", "Mid", first_release_date="2025-01-01"),
            _ri("RG-NEW", "mbid-a", "New", first_release_date="2026-01-01"),
        ],
        ["rg-old", "rg-mid", "rg-new"],
    )
    page1, total = await store.list_new_releases_for_user("user-a", 2, 0)
    assert total == 3
    assert [i.title for i in page1] == ["New", "Mid"]
    page2, _ = await store.list_new_releases_for_user("user-a", 2, 2)
    assert [i.title for i in page2] == ["Old"]


@pytest.mark.asyncio
async def test_unseen_count_no_marker_counts_all(store: FollowStore, tmp_path: Path):
    _seed_library_files(tmp_path / "library.db", owned_rg_mbids=[])
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.seed_baseline("mbid-a", [])
    await store.record_new_releases(
        "mbid-a",
        [
            _ri("RG-1", "mbid-a", "One", first_release_date="2026-01-01"),
            _ri("RG-2", "mbid-a", "Two", first_release_date="2026-02-01"),
        ],
        ["rg-1", "rg-2"],
    )
    assert await store.count_unseen_new_releases_for_user("user-a") == 2


@pytest.mark.asyncio
async def test_mark_seen_zeroes_then_later_discovery_counts(store: FollowStore, tmp_path: Path):
    _seed_library_files(tmp_path / "library.db", owned_rg_mbids=[])
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.seed_baseline("mbid-a", [])
    await store.record_new_releases(
        "mbid-a", [_ri("RG-1", "mbid-a", "One", first_release_date="2026-01-01")], ["rg-1"]
    )
    await store.mark_new_releases_seen("user-a")
    assert await store.count_unseen_new_releases_for_user("user-a") == 0

    await store.record_new_releases(
        "mbid-a", [_ri("RG-2", "mbid-a", "Two", first_release_date="2026-02-01")], ["rg-2"]
    )
    # RG-2 discovered after the marker counts; RG-1 stays seen
    assert await store.count_unseen_new_releases_for_user("user-a") == 1

    await store.mark_new_releases_seen("user-a")  # upsert refreshes the marker
    assert await store.count_unseen_new_releases_for_user("user-a") == 0


@pytest.mark.asyncio
async def test_unseen_count_excludes_owned_and_other_users(store: FollowStore, tmp_path: Path):
    _seed_library_files(tmp_path / "library.db", owned_rg_mbids=["RG-OWNED"])
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.seed_baseline("mbid-a", [])
    await store.seed_baseline("mbid-b", [])
    await store.record_new_releases(
        "mbid-a",
        [
            _ri("RG-NEW", "mbid-a", "Wanted", first_release_date="2026-02-01"),
            _ri("RG-OWNED", "mbid-a", "Already Owned", first_release_date="2026-01-01"),
        ],
        ["rg-new", "rg-owned"],
    )
    await store.record_new_releases(
        "mbid-b",
        [_ri("RG-OTHER", "mbid-b", "Not Followed", first_release_date="2026-03-01")],
        ["rg-other"],
    )
    assert await store.count_unseen_new_releases_for_user("user-a") == 1
    assert await store.count_unseen_new_releases_for_user("user-b") == 0


@pytest.mark.asyncio
async def test_seen_marker_cascades_on_user_delete(store: FollowStore, tmp_path: Path):
    await store.mark_new_releases_seen("user-a")
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM auth_users WHERE id = ?", ("user-a",))
        conn.commit()
        remaining = conn.execute(
            "SELECT COUNT(*) FROM user_new_release_seen WHERE user_id = ?", ("user-a",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert remaining == 0


@pytest.mark.asyncio
async def test_cascade_on_user_delete(store: FollowStore, tmp_path: Path):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.upsert_approval("user-a", "MBID-A", "Radiohead", "pending")
    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM auth_users WHERE id = ?", ("user-a",))
        conn.commit()
    finally:
        conn.close()
    assert (await store.get_follow_state("user-a", "MBID-A")).followed is False
    assert await store.get_approval("user-a", "MBID-A") is None


@pytest.mark.asyncio
async def test_list_followers_returns_every_follower(store: FollowStore):
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    await store.follow_artist("user-b", "MBID-A", "Radiohead")
    await store.follow_artist("user-b", "MBID-X", "Other")
    assert await store.list_followers("mbid-a") == ["user-a", "user-b"]
    assert await store.list_followers("mbid-x") == ["user-b"]
    assert await store.list_followers("mbid-none") == []


@pytest.mark.asyncio
async def test_recent_releases_log_includes_owned_with_flag(
    store: FollowStore, tmp_path: Path
):
    """The LOG view (hub): windowed by release date, owned albums INCLUDED and
    flagged - unlike the to-do view, which hides them."""
    from datetime import date, timedelta

    _seed_library_files(tmp_path / "library.db", ["rg-owned"])
    await store.follow_artist("user-a", "MBID-A", "Radiohead")
    recent = (date.today() - timedelta(days=3)).isoformat()
    old = (date.today() - timedelta(days=90)).isoformat()
    await store.record_new_releases(
        "mbid-a",
        [
            _ri("RG-OWNED", "mbid-a", "Grabbed Album", first_release_date=recent),
            _ri("RG-NEW", "mbid-a", "Fresh Album", first_release_date=recent),
            _ri("RG-OLD", "mbid-a", "Ancient Album", first_release_date=old),
            _ri("RG-DATELESS", "mbid-a", "Dateless Album"),  # falls back to discovered_at
        ],
        [],
    )

    items, total = await store.list_recent_releases_for_user("user-a", days=30, limit=10)
    assert total == 3  # the 90-day-old release is outside the window
    by_title = {i.title: i for i in items}
    assert set(by_title) == {"Grabbed Album", "Fresh Album", "Dateless Album"}
    assert by_title["Grabbed Album"].in_library is True  # owned but still listed
    assert by_title["Fresh Album"].in_library is False
    assert by_title["Dateless Album"].in_library is False

    # the to-do view still hides the owned album
    todo, _ = await store.list_new_releases_for_user("user-a", 10, 0)
    assert "Grabbed Album" not in {i.title for i in todo}

    # other users see nothing (join is per-user)
    assert (await store.list_recent_releases_for_user("user-b", 30, 10))[1] == 0
