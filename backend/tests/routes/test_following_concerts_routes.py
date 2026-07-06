"""Concerts routes (.dev-notes/Events): 401 matrix for every endpoint,
city replace-all semantics (order, radius clamping, blank-name rejection),
per-user city filtering (radius hit/miss + coordinate-less name fallback),
the configured flag, unseen-count/seen behavior, and the city-search proxy's
503-on-provider-failure contract (never a silent [])."""

import asyncio
import sqlite3
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from api.v1.routes.following import router
from core.dependencies import get_events_service, get_geocoding_repository
from core.exceptions import GeocodingApiError
from infrastructure.persistence.events_store import EventsStore
from middleware import _get_current_user
from models.events import LiveEventInput
from repositories.geocoding_repository import GeoCity
from services.events_service import EventsService
from tests.helpers import build_test_client, mock_user

USER_ID = "test-user-id"
MBID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

_ENDPOINTS = [
    ("GET", "/following/concerts"),
    ("GET", "/following/concerts/cities"),
    ("PUT", "/following/concerts/cities"),
    ("GET", "/following/concerts/city-search?q=liverpool"),
    ("GET", "/following/concerts/unseen-count"),
    ("POST", "/following/concerts/seen"),
]

LIVERPOOL = {
    "city_name": "Liverpool",
    "latitude": 53.41,
    "longitude": -2.98,
    "radius_km": 30.0,
    "country_code": "GB",
}


def _make_store(tmp_path: Path) -> EventsStore:
    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE auth_users (
            id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL
        );
        CREATE TABLE user_followed_artists (
            user_id TEXT NOT NULL, artist_mbid TEXT NOT NULL,
            artist_mbid_lower TEXT NOT NULL, artist_name TEXT NOT NULL,
            auto_download INTEGER NOT NULL DEFAULT 0,
            followed_at REAL NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, artist_mbid_lower)
        );
        """
    )
    conn.execute("INSERT INTO auth_users VALUES (?, 'Test', 'user', '2026')", (USER_ID,))
    conn.execute(
        "INSERT INTO user_followed_artists VALUES (?, ?, ?, 'Loathe', 0, 1, 1)",
        (USER_ID, MBID.upper(), MBID),
    )
    conn.commit()
    conn.close()
    return EventsStore(db_path=db_path, write_lock=threading.Lock())


def _event(event_id: str, **overrides) -> LiveEventInput:
    fields = {
        "source": "ticketmaster",
        "source_event_id": event_id,
        "artist_mbid_lower": MBID,
        "artist_name": "Loathe",
        "event_name": "Loathe Live",
        "local_date": "2099-08-28",
        "status": "scheduled",
        "match_confidence": "mbid",
        "venue_name": "O2 Academy",
        "city": "Liverpool",
        "country_code": "GB",
        "latitude": 53.402,
        "longitude": -2.979,
        "ticket_url": "https://tickets.example/x",
    }
    fields.update(overrides)
    return LiveEventInput(**fields)


class _Prefs:
    def __init__(self, ready: bool = True, scope: str = "followed"):
        self._ready = ready
        self._scope = scope

    def is_events_source_ready(self) -> bool:
        return self._ready

    def get_events_settings_raw(self):
        from api.v1.schemas.settings import EventsSettings

        return EventsSettings(enabled=self._ready, sweep_scope=self._scope)


def _client(
    tmp_path: Path,
    *,
    authed: bool = True,
    ready: bool = True,
    scope: str = "followed",
    geocode=None,
):
    app = FastAPI()
    app.include_router(router)
    store = _make_store(tmp_path)
    service = EventsService(events_store=store, preferences=_Prefs(ready, scope))
    app.dependency_overrides[get_events_service] = lambda: service
    geocode = geocode or AsyncMock()
    app.dependency_overrides[get_geocoding_repository] = lambda: geocode
    if authed:
        app.dependency_overrides[_get_current_user] = lambda: mock_user(user_id=USER_ID)
    client = build_test_client(app)
    client.events_store = store  # type: ignore[attr-defined] - test-side handle
    return client


@pytest.mark.parametrize("method,path", _ENDPOINTS)
def test_unauthenticated_gets_401(tmp_path, method, path):
    client = _client(tmp_path, authed=False)
    body = {"items": []} if method == "PUT" else None
    assert client.request(method, path, json=body).status_code == 401


def test_cities_replace_all_roundtrip(tmp_path):
    client = _client(tmp_path)
    chester = {"city_name": "Chester", "latitude": 53.19, "longitude": -2.89,
               "radius_km": 900.0, "country_code": "GB"}
    response = client.put(
        "/following/concerts/cities", json={"items": [LIVERPOOL, chester]}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [c["city_name"] for c in items] == ["Liverpool", "Chester"]
    assert items[1]["radius_km"] == 500.0  # clamped to MAX_RADIUS_KM

    response = client.put("/following/concerts/cities", json={"items": [LIVERPOOL]})
    assert [c["city_name"] for c in response.json()["items"]] == ["Liverpool"]
    assert client.get("/following/concerts/cities").json()["items"][0]["city_name"] == "Liverpool"


def test_out_of_range_coordinates_are_rejected(tmp_path):
    client = _client(tmp_path)
    for bad in ({"latitude": 91.0}, {"latitude": -90.5}, {"longitude": 181.0}):
        response = client.put(
            "/following/concerts/cities", json={"items": [{**LIVERPOOL, **bad}]}
        )
        assert response.status_code == 422, bad


def test_blank_city_names_are_dropped(tmp_path):
    client = _client(tmp_path)
    response = client.put(
        "/following/concerts/cities", json={"items": [{**LIVERPOOL, "city_name": "  "}]}
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_concerts_filtered_by_city_radius_and_name_fallback(tmp_path):
    client = _client(tmp_path)
    client.put("/following/concerts/cities", json={"items": [LIVERPOOL]})
    asyncio.run(
        client.events_store.apply_sweep_result(
            MBID,
            [
                _event("in-radius"),
                _event("too-far", city="London", latitude=51.5, longitude=-0.12),
                # no coordinates: matches by city-name equality
                _event("name-match", latitude=None, longitude=None, city="liverpool"),
                _event("no-coords-no-name", latitude=None, longitude=None, city="Leeds"),
            ],
        )
    )
    payload = client.get("/following/concerts").json()
    assert payload["configured"] is True
    assert payload["total"] == 2
    by_city = {item["matched_city"] for item in payload["items"]}
    assert by_city == {"Liverpool"}
    distances = {item["distance_km"] for item in payload["items"]}
    assert None in distances  # the name-matched row carries no distance
    assert any(d is not None and d < 30 for d in distances)
    assert all(
        item["event_name"] and item["ticket_url"] and item["source_event_id"]
        for item in payload["items"]
    )


def test_no_cities_means_empty_list(tmp_path):
    client = _client(tmp_path)
    asyncio.run(client.events_store.apply_sweep_result(MBID, [_event("e1")]))
    payload = client.get("/following/concerts").json()
    assert payload["items"] == []
    assert payload["total"] == 0


def test_library_scope_shows_unfollowed_library_artists(tmp_path):
    client = _client(tmp_path, scope="library")
    client.put("/following/concerts/cities", json={"items": [LIVERPOOL]})
    asyncio.run(
        client.events_store.apply_sweep_result(
            "mbid-unfollowed",
            [_event("lib-1", artist_mbid_lower="mbid-unfollowed", artist_name="Crawlers")],
        )
    )
    payload = client.get("/following/concerts").json()
    assert payload["total"] == 1
    assert payload["items"][0]["artist_name"] == "Crawlers"
    assert payload["items"][0]["artist_mbid"] == "mbid-unfollowed"

    # followed scope hides the same row (no follow joins it)
    (tmp_path / "followed").mkdir()
    followed_client = _client(tmp_path / "followed", scope="followed")
    followed_client.put("/following/concerts/cities", json={"items": [LIVERPOOL]})
    asyncio.run(
        followed_client.events_store.apply_sweep_result(
            "mbid-unfollowed",
            [_event("lib-1", artist_mbid_lower="mbid-unfollowed", artist_name="Crawlers")],
        )
    )
    assert followed_client.get("/following/concerts").json()["total"] == 0


def test_not_configured_flag_surfaces(tmp_path):
    client = _client(tmp_path, ready=False)
    assert client.get("/following/concerts").json()["configured"] is False


def test_unseen_count_and_seen_clear(tmp_path):
    client = _client(tmp_path)
    client.put("/following/concerts/cities", json={"items": [LIVERPOOL]})
    asyncio.run(client.events_store.apply_sweep_result(MBID, [_event("e1")]))
    assert client.get("/following/concerts/unseen-count").json()["count"] == 1
    assert client.post("/following/concerts/seen").json()["count"] == 0
    assert client.get("/following/concerts/unseen-count").json()["count"] == 0


def test_city_search_proxies_geocoder(tmp_path):
    geocode = AsyncMock()
    geocode.search_cities.return_value = [
        GeoCity(name="Liverpool", latitude=53.41, longitude=-2.98,
                country_code="GB", country="United Kingdom", admin1="England"),
        GeoCity(name="", latitude=0, longitude=0),  # nameless rows dropped
    ]
    client = _client(tmp_path, geocode=geocode)
    payload = client.get("/following/concerts/city-search?q=liverpool").json()
    assert payload["items"] == [
        {
            "name": "Liverpool", "latitude": 53.41, "longitude": -2.98,
            "country_code": "GB", "country": "United Kingdom", "region": "England",
        }
    ]


def test_city_search_provider_failure_is_503_not_empty(tmp_path):
    geocode = AsyncMock()
    geocode.search_cities.side_effect = GeocodingApiError("down")
    client = _client(tmp_path, geocode=geocode)
    response = client.get("/following/concerts/city-search?q=liverpool")
    assert response.status_code == 503


def test_city_search_requires_min_query_length(tmp_path):
    client = _client(tmp_path)
    assert client.get("/following/concerts/city-search?q=l").status_code == 422
