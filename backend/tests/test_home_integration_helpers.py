"""Tests for HomeIntegrationHelpers - all 8 integration checks + resolve_source."""

import pytest
from unittest.mock import MagicMock

from services.home.integration_helpers import HomeIntegrationHelpers


def _make_prefs(**overrides):
    prefs = MagicMock()

    lb = MagicMock()
    lb.enabled = overrides.get("lb_enabled", True)
    lb.username = overrides.get("lb_username", "testuser")
    lb.user_token = "tok"
    prefs.get_listenbrainz_connection.return_value = lb

    jf = MagicMock()
    jf.enabled = overrides.get("jf_enabled", False)
    jf.jellyfin_url = overrides.get("jf_url", "")
    jf.api_key = overrides.get("jf_api_key", "")
    prefs.get_jellyfin_connection.return_value = jf

    dc = MagicMock()
    dc.enabled = overrides.get("dc_enabled", False)
    dc.url = overrides.get("dc_url", "")
    prefs.get_download_client_settings.return_value = dc

    yt = MagicMock()
    yt.enabled = overrides.get("yt_enabled", False)
    yt.api_enabled = overrides.get("yt_api_enabled", False)
    yt.has_valid_api_key = MagicMock(return_value=overrides.get("yt_valid_key", False))
    prefs.get_youtube_connection.return_value = yt

    lf = MagicMock()
    lf.enabled = overrides.get("lf_enabled", False)
    lf.music_path = overrides.get("lf_music_path", "")
    prefs.get_local_files_connection.return_value = lf

    nd = MagicMock()
    nd.enabled = overrides.get("nd_enabled", False)
    nd.navidrome_url = overrides.get("nd_url", "")
    nd.username = overrides.get("nd_username", "")
    nd.password = overrides.get("nd_password", "")
    prefs.get_navidrome_connection.return_value = nd

    lfm = MagicMock()
    lfm.enabled = overrides.get("lfm_enabled", False)
    lfm.username = overrides.get("lfm_username", "")
    prefs.get_lastfm_connection.return_value = lfm
    prefs.is_lastfm_enabled.return_value = overrides.get("lfm_enabled", False)

    source = MagicMock()
    source.source = overrides.get("primary_source", "listenbrainz")
    prefs.get_primary_music_source.return_value = source

    return prefs


class TestIntegrationFlags:
    def test_listenbrainz_enabled(self):
        h = HomeIntegrationHelpers(_make_prefs(lb_enabled=True, lb_username="u"))
        assert h.is_listenbrainz_enabled() is True

    def test_listenbrainz_disabled_no_username(self):
        h = HomeIntegrationHelpers(_make_prefs(lb_enabled=True, lb_username=""))
        assert h.is_listenbrainz_enabled() is False

    def test_jellyfin_enabled(self):
        h = HomeIntegrationHelpers(
            _make_prefs(jf_enabled=True, jf_url="http://jf", jf_api_key="key")
        )
        assert h.is_jellyfin_enabled() is True

    def test_jellyfin_disabled_missing_url(self):
        h = HomeIntegrationHelpers(
            _make_prefs(jf_enabled=True, jf_url="", jf_api_key="key")
        )
        assert h.is_jellyfin_enabled() is False

    def test_download_client_configured(self):
        h = HomeIntegrationHelpers(
            _make_prefs(dc_enabled=True, dc_url="http://slskd")
        )
        assert h.is_download_client_configured() is True

    def test_download_client_not_configured(self):
        h = HomeIntegrationHelpers(_make_prefs())
        assert h.is_download_client_configured() is False

    def test_library_always_configured(self):
        h = HomeIntegrationHelpers(_make_prefs())
        assert h.is_library_configured() is True

    def test_youtube_enabled(self):
        h = HomeIntegrationHelpers(_make_prefs(yt_enabled=True))
        assert h.is_youtube_enabled() is True

    def test_youtube_api_enabled(self):
        h = HomeIntegrationHelpers(
            _make_prefs(yt_enabled=True, yt_api_enabled=True, yt_valid_key=True)
        )
        assert h.is_youtube_api_enabled() is True

    def test_local_files_capability_always_present(self):
        # Native library engine is always present; actual files refined per-request via has_any_files().
        h = HomeIntegrationHelpers(_make_prefs())
        assert h.is_local_files_enabled() is True

    def test_navidrome_enabled(self):
        h = HomeIntegrationHelpers(
            _make_prefs(
                nd_enabled=True, nd_url="http://nd", nd_username="u", nd_password="p"
            )
        )
        assert h.is_navidrome_enabled() is True

    def test_navidrome_disabled_missing_password(self):
        h = HomeIntegrationHelpers(
            _make_prefs(nd_enabled=True, nd_url="http://nd", nd_username="u", nd_password="")
        )
        assert h.is_navidrome_enabled() is False

    def test_lastfm_enabled(self):
        h = HomeIntegrationHelpers(_make_prefs(lfm_enabled=True))
        assert h.is_lastfm_enabled() is True


class TestResolveSource:
    def test_explicit_listenbrainz(self):
        h = HomeIntegrationHelpers(
            _make_prefs(lb_enabled=True, lb_username="u", primary_source="lastfm")
        )
        assert h.resolve_source("listenbrainz") == "listenbrainz"

    def test_explicit_lastfm(self):
        h = HomeIntegrationHelpers(
            _make_prefs(lfm_enabled=True, primary_source="listenbrainz")
        )
        assert h.resolve_source("lastfm") == "lastfm"

    def test_none_uses_global(self):
        h = HomeIntegrationHelpers(_make_prefs(primary_source="lastfm", lfm_enabled=True))
        assert h.resolve_source(None) == "lastfm"

    def test_fallback_to_lastfm_when_lb_disabled(self):
        h = HomeIntegrationHelpers(
            _make_prefs(
                lb_enabled=False, lb_username="", lfm_enabled=True, primary_source="listenbrainz"
            )
        )
        assert h.resolve_source(None) == "lastfm"

    def test_fallback_to_lb_when_lfm_disabled(self):
        h = HomeIntegrationHelpers(
            _make_prefs(
                lb_enabled=True, lb_username="u", lfm_enabled=False, primary_source="lastfm"
            )
        )
        assert h.resolve_source(None) == "listenbrainz"


class TestExecuteTasks:
    @pytest.mark.asyncio
    async def test_execute_tasks_returns_results(self):
        h = HomeIntegrationHelpers(_make_prefs())

        async def task_a():
            return "a_result"

        async def task_b():
            return "b_result"

        results = await h.execute_tasks({"a": task_a(), "b": task_b()})
        assert results["a"] == "a_result"
        assert results["b"] == "b_result"

    @pytest.mark.asyncio
    async def test_execute_tasks_handles_failures(self):
        h = HomeIntegrationHelpers(_make_prefs())

        async def good():
            return "ok"

        async def bad():
            raise ValueError("boom")

        results = await h.execute_tasks({"good": good(), "bad": bad()})
        assert results["good"] == "ok"
        assert results["bad"] is None

    @pytest.mark.asyncio
    async def test_execute_tasks_empty(self):
        h = HomeIntegrationHelpers(_make_prefs())
        results = await h.execute_tasks({})
        assert results == {}
