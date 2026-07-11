import threading

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI

from api.v1.routes.me_connections import router
from core.dependencies import (
    get_per_user_client_factory,
    get_preferences_service,
    get_user_section_prefs_store,
)
from infrastructure.persistence.user_section_prefs_store import UserSectionPrefsStore
from services.section_catalog import DISCOVER_SECTIONS, HOME_SECTIONS, SIDEBAR_SECTIONS
from tests.helpers import build_test_client, override_user_auth

_UID = "test-user-id"


@pytest.fixture
def store(tmp_path):
    return UserSectionPrefsStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())


@pytest.fixture
def client_factory():
    factory = MagicMock()
    factory.is_listenbrainz_linked = AsyncMock(return_value=True)
    factory.is_lastfm_linked = AsyncMock(return_value=False)
    return factory


@pytest.fixture
def client(store, client_factory):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_section_prefs_store] = lambda: store
    app.dependency_overrides[get_per_user_client_factory] = lambda: client_factory
    app.dependency_overrides[get_preferences_service] = lambda: MagicMock()
    override_user_auth(app, user_id=_UID)
    return build_test_client(app)


class TestGetSectionPrefs:
    def test_returns_full_catalog_default_enabled(self, client):
        resp = client.get("/me/section-prefs")
        assert resp.status_code == 200
        pages = resp.json()["pages"]
        assert {s["key"] for s in pages["home"]} == {s.key for s in HOME_SECTIONS}
        assert {s["key"] for s in pages["discover"]} == {s.key for s in DISCOVER_SECTIONS}
        assert {s["key"] for s in pages["sidebar"]} == {s.key for s in SIDEBAR_SECTIONS}
        assert all(s["enabled"] for s in pages["home"])
        assert all(s["enabled"] for s in pages["discover"])
        assert all(s["enabled"] for s in pages["sidebar"])
        # sidebar entries have no service requirement: always available
        assert all(s["available"] for s in pages["sidebar"])

    def test_availability_reflects_user_links(self, client):
        # fixture: LB linked, Last.fm not linked
        resp = client.get("/me/section-prefs")
        discover = resp.json()["pages"]["discover"]
        by_key = {s["key"]: s for s in discover}
        assert by_key["weekly_exploration"]["available"] is True
        assert by_key["lastfm_weekly_artist_chart"]["available"] is False
        assert by_key["lastfm_weekly_artist_chart"]["requires"] == "lastfm"
        # library-backed sections are always available (native engine)
        assert by_key["daily_mixes"]["available"] is True

    def test_items_carry_zone_metadata(self, client):
        resp = client.get("/me/section-prefs")
        home = resp.json()["pages"]["home"]
        assert all(s["zone"] for s in home)


class TestPutSectionPrefs:
    def test_disable_and_reenable_round_trip(self, client):
        sections = [
            {"key": "trending_artists", "enabled": False},
            {"key": "popular_albums", "enabled": True},
        ]
        resp = client.put("/me/section-prefs", json={"page": "home", "sections": sections})
        assert resp.status_code == 200
        home = {s["key"]: s["enabled"] for s in resp.json()["pages"]["home"]}
        assert home["trending_artists"] is False
        assert home["popular_albums"] is True

        # re-enable via a fresh full save
        resp = client.put(
            "/me/section-prefs",
            json={"page": "home", "sections": [{"key": "trending_artists", "enabled": True}]},
        )
        home = {s["key"]: s["enabled"] for s in resp.json()["pages"]["home"]}
        assert home["trending_artists"] is True

    def test_sidebar_round_trip(self, client):
        resp = client.put(
            "/me/section-prefs",
            json={"page": "sidebar", "sections": [{"key": "jellyfin", "enabled": False}]},
        )
        assert resp.status_code == 200
        sidebar = {s["key"]: s["enabled"] for s in resp.json()["pages"]["sidebar"]}
        assert sidebar["jellyfin"] is False
        assert sidebar["navidrome"] is True

        # GET reflects the saved state, other pages untouched
        resp = client.get("/me/section-prefs")
        pages = resp.json()["pages"]
        sidebar = {s["key"]: s["enabled"] for s in pages["sidebar"]}
        assert sidebar["jellyfin"] is False
        assert all(s["enabled"] for s in pages["home"])

    def test_sidebar_unknown_key_rejected(self, client):
        resp = client.put(
            "/me/section-prefs",
            json={"page": "sidebar", "sections": [{"key": "spotify", "enabled": False}]},
        )
        assert resp.status_code == 422

    def test_unknown_key_rejected(self, client):
        resp = client.put(
            "/me/section-prefs",
            json={"page": "home", "sections": [{"key": "nonsense_section", "enabled": False}]},
        )
        assert resp.status_code == 422

    def test_invalid_page_rejected(self, client):
        resp = client.put(
            "/me/section-prefs",
            json={"page": "profile", "sections": []},
        )
        assert resp.status_code == 422

    def test_put_response_only_contains_saved_page(self, client):
        resp = client.put(
            "/me/section-prefs",
            json={"page": "discover", "sections": [{"key": "daily_mixes", "enabled": False}]},
        )
        pages = resp.json()["pages"]
        assert set(pages.keys()) == {"discover"}
