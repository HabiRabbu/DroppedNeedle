from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import msgspec
import pytest

from api.v1.schemas.library_management import (
    LibraryManagementProfile,
    NamingScriptSettings,
    ProfileNotificationSettings,
)
from core.exceptions import ExternalServiceError, JellyfinAuthError
from models.library_management import LibraryManagementExternalRefreshDelivery
from models.library_management_planning import PinnedLibraryManagementProfile
from services.native.library_management_notification_service import (
    LibraryManagementNotificationService,
)
from services.native.library_operation_supervisor import LibraryOperationSupervisor
from services.native.library_management_post_commit_service import (
    LibraryManagementPostCommitService,
)


def _pending() -> LibraryManagementExternalRefreshDelivery:
    return LibraryManagementExternalRefreshDelivery(
        id="delivery-1",
        operation_job_id="operation-1",
        target="jellyfin",
        max_attempts=4,
        retry_delay_seconds=30,
        created_at=1,
        updated_at=1,
    )


@pytest.mark.asyncio
async def test_notification_failure_is_retryable_and_does_not_touch_parent() -> None:
    store = AsyncMock()
    store.claim_library_management_external_refresh.return_value = _pending()
    jellyfin = AsyncMock()
    jellyfin.refresh_library.side_effect = ExternalServiceError("offline")
    service = LibraryManagementNotificationService(store, lambda: jellyfin)

    operation_id = await service.run_once("worker-1", now=10.0)

    assert operation_id == "operation-1"
    store.finish_library_management_external_refresh.assert_awaited_once_with(
        "delivery-1",
        "worker-1",
        succeeded=False,
        retryable=True,
        failure_code="EXTERNAL_REFRESH_FAILED",
        now=10.0,
    )
    store.finish_operation_job.assert_not_called()


@pytest.mark.asyncio
async def test_notification_auth_failure_is_permanent() -> None:
    store = AsyncMock()
    store.claim_library_management_external_refresh.return_value = _pending()
    jellyfin = AsyncMock()
    jellyfin.refresh_library.side_effect = JellyfinAuthError("unauthorized")
    service = LibraryManagementNotificationService(store, lambda: jellyfin)

    await service.run_once("worker-1", now=10.0)

    store.finish_library_management_external_refresh.assert_awaited_once_with(
        "delivery-1",
        "worker-1",
        succeeded=False,
        retryable=False,
        failure_code="EXTERNAL_REFRESH_AUTH_FAILED",
        now=10.0,
    )


@pytest.mark.asyncio
async def test_existing_operation_supervisor_dispatches_delivery_when_idle() -> None:
    store = AsyncMock()
    store.claim_operation_job.return_value = None
    operations = AsyncMock()
    expected = MagicMock()
    operations.get.return_value = expected
    notifications = AsyncMock()
    notifications.run_once.return_value = "operation-1"
    supervisor = LibraryOperationSupervisor(
        store,
        operations,
        AsyncMock(),
        AsyncMock(),
        notifications=notifications,
    )

    result = await supervisor.run_once("worker-1", now=10.0)

    assert result is expected
    notifications.run_once.assert_awaited_once_with("worker-1", now=10.0)
    operations.get.assert_awaited_once_with("operation-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured", "expected_state", "expected_failure"),
    [
        (True, "pending", None),
        (False, "unavailable", "EXTERNAL_REFRESH_NOT_CONFIGURED"),
    ],
)
async def test_post_commit_enqueues_verified_jellyfin_delivery(
    configured: bool, expected_state: str, expected_failure: str | None
) -> None:
    pinned = PinnedLibraryManagementProfile(
        profile=LibraryManagementProfile(
            id="profile-1",
            name="Profile",
            notification=ProfileNotificationSettings(refresh_external_servers=True),
        ),
        naming_script=NamingScriptSettings(
            id="naming-1", name="Naming", source="$title"
        ),
    )
    store = AsyncMock()
    store.get_target_tracks_by_ids.return_value = {
        "track-1": {
            "provider_release_group_mbid": "release-group-1",
            "provider_album_artist_mbid": "artist-1",
            "provider_artist_mbid": "artist-1",
        }
    }
    store.get_track_management_state.return_value = SimpleNamespace(
        last_operation_job_id="operation-1"
    )
    store.get_library_management_job_snapshot.return_value = SimpleNamespace(
        profile_snapshot_json=msgspec.json.encode(pinned).decode()
    )
    preferences = MagicMock()
    preferences.get_library_management_settings_raw.return_value = SimpleNamespace(
        external_refresh=SimpleNamespace(
            enabled=True,
            jellyfin_enabled=True,
            plex_enabled=False,
            navidrome_enabled=False,
            retry_attempts=3,
            retry_delay_seconds=30,
        )
    )
    memory_cache = AsyncMock()
    disk_cache = AsyncMock()
    discovery = AsyncMock()
    jellyfin = MagicMock()
    jellyfin.is_configured.return_value = configured
    service = LibraryManagementPostCommitService(
        store,
        preferences,
        memory_cache,
        disk_cache,
        discovery,
        lambda: jellyfin,
    )

    await service.after_commit({"track-1"}, {"album-1"})

    delivery = store.ensure_library_management_external_refresh.await_args.args[0]
    assert delivery.operation_job_id == "operation-1"
    assert delivery.target == "jellyfin"
    assert delivery.state == expected_state
    assert delivery.failure_code == expected_failure
    assert delivery.max_attempts == 4
    memory_cache.clear_prefix.assert_awaited()
    disk_cache.delete_album.assert_awaited_once_with("release-group-1")
    disk_cache.delete_artist.assert_awaited_once_with("artist-1")
    discovery.mark_discover_stale.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_commit_skips_external_delivery_when_profile_opted_out() -> None:
    pinned = PinnedLibraryManagementProfile(
        profile=LibraryManagementProfile(id="profile-1", name="Profile"),
        naming_script=NamingScriptSettings(
            id="naming-1", name="Naming", source="$title"
        ),
    )
    store = AsyncMock()
    store.get_target_tracks_by_ids.return_value = {}
    store.get_track_management_state.return_value = SimpleNamespace(
        last_operation_job_id="operation-1"
    )
    store.get_library_management_job_snapshot.return_value = SimpleNamespace(
        profile_snapshot_json=msgspec.json.encode(pinned).decode()
    )
    service = LibraryManagementPostCommitService(
        store,
        MagicMock(),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        lambda: MagicMock(),
    )

    await service.after_commit({"track-1"}, {"album-1"})

    store.ensure_library_management_external_refresh.assert_not_awaited()
