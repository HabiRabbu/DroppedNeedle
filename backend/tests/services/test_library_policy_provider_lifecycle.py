from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from core.dependencies import cleanup, service_providers


def test_target_download_graph_uses_new_naming_template_after_invalidation(
    monkeypatch,
) -> None:
    state = {"template": "{track:02d} {title}.{ext}"}
    monkeypatch.setattr(
        service_providers,
        "get_target_file_processor",
        MagicMock(return_value=object()),
    )
    monkeypatch.setattr(
        service_providers, "get_target_library_repository", lambda: object()
    )
    monkeypatch.setattr(service_providers, "get_target_album_service", lambda: object())
    monkeypatch.setattr(service_providers, "get_cache", lambda: object())
    monkeypatch.setattr(service_providers, "get_disk_cache", lambda: object())
    monkeypatch.setattr(
        service_providers,
        "_build_target_import_invalidation",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        service_providers,
        "_build_download_orchestrator",
        lambda **_kwargs: SimpleNamespace(naming_template=state["template"]),
    )
    service_providers.get_target_download_orchestrator.cache_clear()

    existing = service_providers.get_target_download_orchestrator()
    state["template"] = "{track:02d} - {title}.{ext}"
    cleanup.clear_library_policy_dependent_caches()
    replacement = service_providers.get_target_download_orchestrator()

    assert existing.naming_template == "{track:02d} {title}.{ext}"
    assert replacement.naming_template == "{track:02d} - {title}.{ext}"
    assert replacement is not existing

    service_providers.get_target_download_orchestrator.cache_clear()
