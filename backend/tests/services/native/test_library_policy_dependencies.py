from pathlib import Path
from types import SimpleNamespace

from api.v1.schemas.library_policies import LibraryRootSettings, TypedLibrarySettings
from core.dependencies import service_providers
from core.task_registry import TaskRegistry


def test_resolver_provider_refreshes_without_duplicate_task_registration(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    state = {"policy": "automatic"}

    class Preferences:
        def get_typed_library_settings(self):
            return TypedLibrarySettings(
                library_roots=[
                    LibraryRootSettings(
                        id="root-1",
                        path=str(root),
                        label="Music",
                        policy=state["policy"],
                    )
                ]
            )

    monkeypatch.setattr(service_providers, "get_preferences_service", Preferences)
    monkeypatch.setattr(
        service_providers,
        "get_library_db",
        lambda: SimpleNamespace(get_library_path_mapping_sources=None),
    )
    service_providers.get_library_policy_resolver.cache_clear()
    service_providers.get_library_policy_service.cache_clear()
    TaskRegistry.get_instance().reset()

    service = service_providers.get_library_policy_service()
    first = service_providers.get_library_policy_resolver()
    state["policy"] = "excluded"
    service_providers.get_library_policy_resolver.cache_clear()
    second = service_providers.get_library_policy_resolver()

    assert first is not second
    assert first.resolve(root / "track.flac").policy == "automatic"
    assert second.resolve(root / "track.flac").policy == "excluded"
    assert service.get_settings().library_roots[0].policy == "excluded"
    assert TaskRegistry.get_instance().get_all() == {}

    service_providers.get_library_policy_resolver.cache_clear()
    service_providers.get_library_policy_service.cache_clear()
