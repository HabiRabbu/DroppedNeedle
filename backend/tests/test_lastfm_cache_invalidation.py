"""Tests that Last.fm cache invalidation covers all dependent service factories."""

from unittest.mock import MagicMock, patch

from core import dependencies as deps
from core.dependencies import cleanup as _cleanup_mod


LASTFM_DEPENDENT_FACTORIES = [
    "get_artist_discovery_service",
    "get_target_artist_discovery_service",
    "get_album_discovery_service",
    "get_target_album_discovery_service",
    "get_artist_enrichment_service",
    "get_album_enrichment_service",
    "get_search_enrichment_service",
    "get_scrobble_service",
    "get_home_charts_service",
    "get_target_home_charts_service",
    "get_home_service",
    "get_target_home_service",
    "get_discover_service",
    "get_target_discover_service",
    "get_target_discover_queue_manager",
    "get_lastfm_auth_service",
    "get_genre_projection_service",
    "get_target_wrapped_service",
]


def test_clear_lastfm_dependent_caches_clears_all_consumers():
    mocks = {}
    patches = []
    for name in LASTFM_DEPENDENT_FACTORIES:
        mock_fn = MagicMock()
        mock_fn.cache_clear = MagicMock()
        # Patch in the cleanup module's namespace where the function is actually called
        p = patch.object(_cleanup_mod, name, mock_fn)
        p.start()
        patches.append(p)
        mocks[name] = mock_fn

    try:
        deps.clear_lastfm_dependent_caches()
        for name, mock_fn in mocks.items():
            assert mock_fn.cache_clear.called, f"{name}.cache_clear() was not called"
    finally:
        for p in patches:
            p.stop()


def test_all_lastfm_factories_are_tracked():
    """Verify every @lru_cache factory that receives lastfm_repo is in the clear list."""
    import ast
    import inspect

    # After the dependencies package split, scan the sub-module that holds
    # service providers (where lastfm_repo usage lives).
    from core.dependencies import service_providers as svc_mod

    source = inspect.getsource(svc_mod)
    tree = ast.parse(source)

    factories_with_lastfm = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("get_"):
            continue
        body_source = ast.get_source_segment(source, node)
        if body_source and "get_lastfm_repository()" in body_source:
            if node.name != "get_lastfm_repository":
                factories_with_lastfm.add(node.name)

    tracked = set(LASTFM_DEPENDENT_FACTORIES)
    missing = factories_with_lastfm - tracked
    assert not missing, (
        f"Factories that use lastfm_repo but are NOT in "
        f"clear_lastfm_dependent_caches: {missing}"
    )
