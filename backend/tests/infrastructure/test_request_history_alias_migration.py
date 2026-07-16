import threading
from pathlib import Path

import pytest

from infrastructure.persistence.mbid_store import MBIDStore
from infrastructure.persistence.request_history import RequestHistoryStore


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["awaiting_approval", "queued"])
async def test_known_release_aliases_merge_into_canonical_request_history(
    tmp_path: Path, status: str
) -> None:
    path = tmp_path / "library.db"
    lock = threading.Lock()
    history = RequestHistoryStore(path, lock)
    aliases = MBIDStore(path, lock)
    await aliases.save_mbid_resolution_map({"release-1": "release-group-1"})
    await history.async_record_request(
        "release-group-1",
        "Old artist",
        "Old album",
        user_id="old-user",
        requested_by_name="Old user",
        initial_status="failed",
    )
    await history.async_record_request(
        "release-1",
        "Current artist",
        "Current album",
        user_id="requester",
        requested_by_name="Requester",
        initial_status=status,
    )

    assert await history.async_canonicalize_known_release_aliases() == 1
    assert await history.async_canonicalize_known_release_aliases() == 0
    assert await history.async_get_record("release-1") is None
    canonical = await history.async_get_record("release-group-1")
    assert canonical is not None
    assert canonical.status == status
    assert canonical.user_id == "requester"
    assert canonical.requested_by_name == "Requester"
    assert canonical.release_mbid == "release-1"


@pytest.mark.asyncio
async def test_canonical_winner_keeps_the_source_release_as_edition(
    tmp_path: Path,
) -> None:
    path = tmp_path / "library.db"
    lock = threading.Lock()
    history = RequestHistoryStore(path, lock)
    aliases = MBIDStore(path, lock)
    await aliases.save_mbid_resolution_map({"release-1": "release-group-1"})
    await history.async_record_request(
        "release-1", "Artist", "Album", user_id="alias-user", initial_status="pending"
    )
    await history.async_record_request(
        "release-group-1",
        "Artist",
        "Album",
        user_id="canonical-user",
        initial_status="downloading",
    )
    await history.async_update_download_task_id("release-group-1", "task-1")

    assert await history.async_canonicalize_known_release_aliases(["release-1"]) == 1
    canonical = await history.async_get_record("release-group-1")
    assert canonical is not None
    assert canonical.status == "downloading"
    assert canonical.user_id == "canonical-user"
    assert canonical.download_task_id == "task-1"
    assert canonical.release_mbid == "release-1"
