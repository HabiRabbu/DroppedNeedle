from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.exceptions import ExternalServiceError
from infrastructure.persistence.navidrome_folder_preferences_store import (
    NavidromeFolderPreference,
)
from services.navidrome_folder_scope_service import NavidromeFolderScopeService

pytestmark = pytest.mark.asyncio


def _service(preference, folders):
    store = SimpleNamespace(get=AsyncMock(return_value=preference), set=AsyncMock())
    repository = SimpleNamespace(
        server_identity="server-1", get_music_folders=AsyncMock(return_value=folders)
    )
    return NavidromeFolderScopeService(store, repository), store, repository


async def test_missing_preference_resolves_to_all():
    service, _, _ = _service(
        NavidromeFolderPreference(), [SimpleNamespace(id="a", name="A")]
    )
    resolution = await service.resolve("alice")
    assert resolution.scope.mode == "all"
    assert resolution.scope.folder_ids == ()
    assert resolution.available_folders == (("a", "A"),)


async def test_stale_selected_folders_fail_closed():
    preference = NavidromeFolderPreference(
        "selected", ("gone",), "server-1", 1.0
    )
    service, _, _ = _service(
        preference, [SimpleNamespace(id="other", name="Other")]
    )
    resolution = await service.resolve("alice")
    assert resolution.scope.folder_ids == ()
    assert resolution.stale_folder_ids == ("gone",)


async def test_server_identity_change_marks_every_selection_stale():
    preference = NavidromeFolderPreference(
        "selected", ("a",), "old-server", 1.0
    )
    service, _, _ = _service(preference, [SimpleNamespace(id="a", name="A")])
    resolution = await service.resolve("alice")
    assert resolution.scope.folder_ids == ()
    assert resolution.stale_folder_ids == ("a",)


async def test_unavailable_read_retains_saved_selection():
    preference = NavidromeFolderPreference(
        "selected", ("a",), "server-1", 1.0
    )
    service, _, repository = _service(preference, [])
    repository.get_music_folders.side_effect = ExternalServiceError("unavailable")
    resolution = await service.resolve("alice")
    assert resolution.source_available is False
    assert resolution.scope.folder_ids == ("a",)


async def test_save_subset_validates_and_canonicalizes():
    preference = NavidromeFolderPreference(
        "selected", ("a", "b"), "server-1", 1.0
    )
    service, store, _ = _service(
        preference,
        [SimpleNamespace(id="a", name="A"), SimpleNamespace(id="b", name="B")],
    )
    await service.save("alice", mode="selected", selected_folder_ids=["b", "a"])
    store.set.assert_awaited_once_with(
        "alice",
        mode="selected",
        selected_folder_ids=("b", "a"),
        server_identity="server-1",
    )


@pytest.mark.parametrize(
    "ids",
    [[], ["a", "a"], ["unknown"]],
)
async def test_invalid_subset_is_not_saved(ids):
    service, store, _ = _service(
        NavidromeFolderPreference(), [SimpleNamespace(id="a", name="A")]
    )
    with pytest.raises(ValueError):
        await service.save("alice", mode="selected", selected_folder_ids=ids)
    store.set.assert_not_awaited()
