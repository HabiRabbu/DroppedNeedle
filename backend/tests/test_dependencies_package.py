"""Tests for the dependencies package structure and registry."""

import importlib

import pytest

from core.dependencies._registry import _singleton_registry, clear_all_singletons


class TestSingletonRegistry:
    def test_registry_has_expected_count(self):
        assert len(_singleton_registry) == 62

    def test_all_entries_have_cache_clear(self):
        for fn in _singleton_registry:
            assert hasattr(fn, "cache_clear"), f"{fn.__name__} missing cache_clear"

    def test_clear_all_singletons_calls_cache_clear(self):
        before = [fn.cache_info().currsize for fn in _singleton_registry]
        clear_all_singletons()
        after = [fn.cache_info().currsize for fn in _singleton_registry]
        assert all(s == 0 for s in after)


class TestReExportCompleteness:
    def test_init_exports_all_providers(self):
        init = importlib.import_module("core.dependencies")
        from core.dependencies import cache_providers, repo_providers, service_providers

        for mod in (cache_providers, repo_providers, service_providers):
            for name in dir(mod):
                obj = getattr(mod, name)
                if name.startswith("get_") and getattr(obj, "__module__", "") == mod.__name__:
                    assert hasattr(init, name), f"{name} not re-exported from __init__"

    def test_init_exports_all_type_aliases(self):
        init = importlib.import_module("core.dependencies")
        from core.dependencies import type_aliases

        for name in dir(type_aliases):
            if name.endswith("Dep"):
                assert hasattr(init, name), f"{name} not re-exported from __init__"

    def test_init_exports_cleanup_functions(self):
        from core.dependencies import (
            init_app_state,
            cleanup_app_state,
            clear_lastfm_dependent_caches,
            clear_listenbrainz_dependent_caches,
            clear_all_singletons,
        )
        assert callable(init_app_state)
        assert callable(cleanup_app_state)
        assert callable(clear_lastfm_dependent_caches)
        assert callable(clear_listenbrainz_dependent_caches)
        assert callable(clear_all_singletons)


class TestSingletonDecorator:
    def test_singleton_caches_return_value(self):
        from core.dependencies._registry import singleton

        call_count = 0

        @singleton
        def my_provider():
            nonlocal call_count
            call_count += 1
            return object()

        a = my_provider()
        b = my_provider()
        assert a is b
        assert call_count == 1

        my_provider.cache_clear()
        c = my_provider()
        assert c is not a
        assert call_count == 2

        # clean up: remove from registry
        _singleton_registry.remove(my_provider)
