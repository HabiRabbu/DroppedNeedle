from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
import pytest

from api.v1.routes.library_contributions import router
from core.dependencies import get_library_contribution_service
from core.exceptions import ValidationError
from middleware import AuthMiddleware, _get_current_curator
from models.library_contribution import (
    ContributionRecord,
    ContributionSourceSelection,
    LocalReleaseSnapshot,
    ReleaseDraft,
    MusicBrainzSeed,
)
from tests.helpers import build_test_client, override_user_auth


def _contribution() -> ContributionRecord:
    return ContributionRecord(
        id="contribution-1",
        local_album_id="album-1",
        created_by_user_id="curator-1",
        updated_by_user_id="curator-1",
        state="draft",
        album_row_revision=1,
        input_revision="input-1",
        local_snapshot=LocalReleaseSnapshot(local_album_id="album-1"),
        draft=ReleaseDraft(),
        source_selection=ContributionSourceSelection(),
    )


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    service = AsyncMock()
    service.create.return_value = _contribution()
    service.get.return_value = _contribution()
    service.update.return_value = _contribution()
    service.rebuild.return_value = _contribution()
    service.cancel.return_value = _contribution()
    service.search_discogs.return_value = []
    service.select_discogs.return_value = _contribution()
    service.remove_discogs.return_value = _contribution()
    service.check_duplicates.return_value = _contribution()
    service.attach_existing.return_value = _contribution()
    service.create_musicbrainz_seed.return_value = MusicBrainzSeed(
        action_url="https://musicbrainz.org/release/add"
    )
    service.consume_musicbrainz_callback.return_value = "contribution-1"
    service.record_manual_result.return_value = _contribution()
    service.retry_verification.return_value = _contribution()
    application.dependency_overrides[get_library_contribution_service] = lambda: service
    return application


def test_all_contribution_routes_require_authentication(app: FastAPI) -> None:
    client = build_test_client(app)
    requests = (
        ("POST", "/library/albums/album-1/contributions", {}),
        ("GET", "/library/contributions/contribution-1", None),
        (
            "PUT",
            "/library/contributions/contribution-1/draft",
            {"expected_row_revision": 1, "draft": {}},
        ),
        (
            "POST",
            "/library/contributions/contribution-1/rebuild",
            {"expected_row_revision": 1},
        ),
        (
            "POST",
            "/library/contributions/contribution-1/musicbrainz/duplicates",
            {"expected_row_revision": 1},
        ),
        (
            "POST",
            "/library/contributions/contribution-1/musicbrainz/attach",
            {
                "expected_row_revision": 1,
                "release_mbid": "11111111-1111-4111-8111-111111111111",
            },
        ),
        (
            "POST",
            "/library/contributions/contribution-1/musicbrainz/seed",
            {"expected_row_revision": 1},
        ),
        (
            "PUT",
            "/library/contributions/contribution-1/musicbrainz/result",
            {
                "expected_row_revision": 1,
                "release_id_or_url": "11111111-1111-4111-8111-111111111111",
            },
        ),
        (
            "POST",
            "/library/contributions/contribution-1/musicbrainz/verify",
            {"expected_row_revision": 1},
        ),
        (
            "POST",
            "/library/contributions/contribution-1/cancel",
            {"expected_row_revision": 1},
        ),
        (
            "POST",
            "/library/contributions/contribution-1/discogs/search",
            {"query": "Album"},
        ),
        (
            "POST",
            "/library/contributions/contribution-1/discogs/select",
            {"expected_row_revision": 1, "release_id_or_url": "249504"},
        ),
        (
            "POST",
            "/library/contributions/contribution-1/discogs/remove",
            {"expected_row_revision": 1},
        ),
    )
    for method, path, body in requests:
        response = client.request(method, path, json=body)
        assert response.status_code == 401, (method, path, response.text)


def test_listener_can_read_but_cannot_mutate_shared_contribution(app: FastAPI) -> None:
    override_user_auth(app, role="user")

    def reject() -> None:
        raise HTTPException(status_code=403, detail="Elevated access required")

    app.dependency_overrides[_get_current_curator] = reject
    client = build_test_client(app)

    assert client.get("/library/contributions/contribution-1").status_code == 200
    assert (
        client.post("/library/albums/album-1/contributions", json={}).status_code == 403
    )
    assert (
        client.post(
            "/library/contributions/contribution-1/cancel",
            json={"expected_row_revision": 1},
        ).status_code
        == 403
    )


def test_trusted_curator_can_create_and_edit(app: FastAPI) -> None:
    override_user_auth(app, role="trusted", user_id="curator-1")
    app.dependency_overrides[_get_current_curator] = lambda: SimpleNamespace(
        id="curator-1", role="trusted"
    )
    client = build_test_client(app)

    created = client.post("/library/albums/album-1/contributions", json={})
    updated = client.put(
        "/library/contributions/contribution-1/draft",
        json={"expected_row_revision": 1, "draft": {}},
    )
    assert created.status_code == 200
    assert updated.status_code == 200
    searched = client.post(
        "/library/contributions/contribution-1/discogs/search",
        json={"query": "Album"},
    )
    selected = client.post(
        "/library/contributions/contribution-1/discogs/select",
        json={"expected_row_revision": 1, "release_id_or_url": "249504"},
    )
    removed = client.post(
        "/library/contributions/contribution-1/discogs/remove",
        json={"expected_row_revision": 1},
    )
    duplicates = client.post(
        "/library/contributions/contribution-1/musicbrainz/duplicates",
        json={"expected_row_revision": 1},
    )
    attached = client.post(
        "/library/contributions/contribution-1/musicbrainz/attach",
        json={
            "expected_row_revision": 1,
            "release_mbid": "11111111-1111-4111-8111-111111111111",
        },
    )
    seed = client.post(
        "/library/contributions/contribution-1/musicbrainz/seed",
        json={"expected_row_revision": 1},
    )
    result = client.put(
        "/library/contributions/contribution-1/musicbrainz/result",
        json={
            "expected_row_revision": 1,
            "release_id_or_url": "11111111-1111-4111-8111-111111111111",
        },
    )
    retry = client.post(
        "/library/contributions/contribution-1/musicbrainz/verify",
        json={"expected_row_revision": 1},
    )
    assert searched.status_code == 200
    assert selected.status_code == 200
    assert removed.status_code == 200
    assert duplicates.status_code == 200
    assert attached.status_code == 200
    assert seed.status_code == 200
    assert result.status_code == 200
    assert retry.status_code == 200
    assert seed.json()["action_url"] == "https://musicbrainz.org/release/add"
    service = app.dependency_overrides[get_library_contribution_service]()
    service.create.assert_awaited_once_with("album-1", "curator-1")


def test_public_callback_only_records_result_and_redirects_safely(app: FastAPI) -> None:
    client = build_test_client(app)
    response = client.get(
        "/library/contributions/musicbrainz/callback",
        params={
            "token": "a" * 43,
            "release_mbid": "11111111-1111-4111-8111-111111111111",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/library/contributions/contribution-1?musicbrainz=returned"
    )
    assert response.headers["cache-control"] == "no-store"
    service = app.dependency_overrides[get_library_contribution_service]()
    service.consume_musicbrainz_callback.assert_awaited_once_with(
        "a" * 43, "11111111-1111-4111-8111-111111111111"
    )
    service.attach_existing.assert_not_awaited()


def test_invalid_public_callback_uses_fixed_error_redirect(app: FastAPI) -> None:
    service = app.dependency_overrides[get_library_contribution_service]()
    service.consume_musicbrainz_callback.side_effect = ValidationError("private detail")
    client = build_test_client(app)

    response = client.get(
        "/library/contributions/musicbrainz/callback?token=bad",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/library?musicbrainz=callback-error"
    assert "private" not in response.text


def test_only_the_exact_musicbrainz_callback_path_is_public() -> None:
    assert AuthMiddleware._is_public(
        "/api/v1/library/contributions/musicbrainz/callback"
    )
    assert not AuthMiddleware._is_public(
        "/api/v1/library/contributions/contribution-1/musicbrainz/callback"
    )
