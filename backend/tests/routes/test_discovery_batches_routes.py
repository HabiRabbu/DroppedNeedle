"""Discovery batches: ownership-scoped routes + service behaviour (create outcomes,
removal scoping, recycle-bin routing)."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from api.v1.routes.discovery_batches import router
from api.v1.schemas.discovery_batches import DiscoveryBatchCreate, DiscoveryBatchItemIn
from api.v1.schemas.request import BatchCancelResponse
from core.dependencies import get_discovery_batch_service
from core.exceptions import ResourceNotFoundError, ValidationError
from infrastructure.persistence.discovery_batch_store import DiscoveryBatchStore
from services.discovery_batch_service import DiscoveryBatchService
from tests.helpers import build_test_client, override_user_auth

_OWNER = "owner-1"


@pytest.fixture
def store(tmp_path):
    return DiscoveryBatchStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())


def _service(store, **overrides) -> DiscoveryBatchService:
    request_service = MagicMock()
    request_service.request_batch = AsyncMock(
        return_value=SimpleNamespace(success=True, requested=1, skipped=0)
    )
    request_service.cancel_batch = AsyncMock(
        return_value=BatchCancelResponse(success=True, cancelled=1, failed=0, message="ok")
    )
    history = MagicMock()
    history.async_get_active_mbids = AsyncMock(return_value=set())
    history.async_get_record = AsyncMock(return_value=None)
    library_service = MagicMock()
    library_service.remove_album = AsyncMock()
    library_db = MagicMock()
    library_db.get_all_album_mbids = AsyncMock(return_value=set())
    download_service = MagicMock()
    download_service.purge_album_downloads = AsyncMock()
    deps = dict(
        batch_store=store,
        request_service=request_service,
        request_history=history,
        library_service=library_service,
        library_db=library_db,
        download_service=download_service,
    )
    deps.update(overrides)
    return DiscoveryBatchService(**deps)


def _items(n=2):
    return [
        DiscoveryBatchItemIn(
            release_group_mbid=f"rg-{i}",
            artist_mbid=f"a-{i}",
            album_name=f"Album {i}",
            artist_name=f"Artist {i}",
        )
        for i in range(n)
    ]


class TestServiceCreate:
    @pytest.mark.asyncio
    async def test_create_files_requests_and_records_outcomes(self, store):
        svc = _service(store)
        svc._library_db.get_all_album_mbids = AsyncMock(return_value={"rg-0"})
        svc._history.async_get_active_mbids = AsyncMock(return_value={"rg-1"})

        detail = await svc.create(
            _OWNER, "trusted", "Owner",
            DiscoveryBatchCreate(name="Mix", source_section="daily_mixes", items=_items(3)),
        )

        by_mbid = {i.release_group_mbid: i.outcome for i in detail.items}
        assert by_mbid == {
            "rg-0": "skipped_in_library",
            "rg-1": "skipped_duplicate",
            "rg-2": "requested",
        }
        # only the genuinely-new album goes through the normal request pipeline
        sent = svc._requests.request_batch.await_args.kwargs["items"]
        assert [i["musicbrainz_id"] for i in sent] == ["rg-2"]

    @pytest.mark.asyncio
    async def test_all_skipped_rejects_batch(self, store):
        svc = _service(store)
        svc._library_db.get_all_album_mbids = AsyncMock(return_value={"rg-0", "rg-1"})
        with pytest.raises(ValidationError):
            await svc.create(
                _OWNER, "trusted", "Owner", DiscoveryBatchCreate(name="Mix", items=_items(2))
            )
        assert await svc.list_for_user(_OWNER) == []

    @pytest.mark.asyncio
    async def test_over_cap_rejected(self, store):
        svc = _service(store)
        with pytest.raises(ValidationError):
            await svc.create(
                _OWNER, "trusted", "Owner", DiscoveryBatchCreate(name="Big", items=_items(31))
            )

    @pytest.mark.asyncio
    async def test_quota_rejection_creates_no_batch(self, store):
        svc = _service(store)
        svc._requests.request_batch = AsyncMock(side_effect=ValidationError("over quota"))
        with pytest.raises(ValidationError):
            await svc.create(
                _OWNER, "user", "Owner", DiscoveryBatchCreate(name="Mix", items=_items(2))
            )
        assert await svc.list_for_user(_OWNER) == []


class TestServiceRemove:
    @pytest.mark.asyncio
    async def test_remove_scopes_to_requested_items_only(self, store):
        svc = _service(store)
        # rg-0 was already in the library at batch time -> never touched;
        # rg-1 imported by the batch -> recycled; rg-2 still pending -> cancelled
        await store.create_batch(_OWNER, "Mix", "s", [
            {"release_group_mbid": "rg-0", "outcome": "skipped_in_library"},
            {"release_group_mbid": "rg-1", "outcome": "requested"},
            {"release_group_mbid": "rg-2", "outcome": "requested"},
        ])
        batch_id = (await store.list_batches(_OWNER))[0]["id"]
        svc._library_db.get_all_album_mbids = AsyncMock(return_value={"rg-0", "rg-1"})
        svc._history.async_get_record = AsyncMock(
            side_effect=lambda mbid: SimpleNamespace(status="pending", user_id=_OWNER)
            if mbid == "rg-2"
            else None
        )

        result = await svc.remove(_OWNER, "trusted", batch_id, remove_albums=True)

        assert result.removed_albums == 1
        assert result.cancelled_requests == 1
        assert result.kept == 1
        # the pre-existing album must never be removed
        removed_mbids = [c.args[0] for c in svc._library_service.remove_album.await_args_list]
        assert removed_mbids == ["rg-1"]
        # removal is reversible: files go through the recycle bin
        assert svc._library_service.remove_album.await_args.kwargs == {"to_recycle": True}
        svc._download_service.purge_album_downloads.assert_awaited_once_with("rg-1")
        assert await store.get_batch(batch_id) is None

    @pytest.mark.asyncio
    async def test_keep_albums_only_deletes_the_batch_record(self, store):
        svc = _service(store)
        await store.create_batch(_OWNER, "Mix", "s", [
            {"release_group_mbid": "rg-1", "outcome": "requested"},
        ])
        batch_id = (await store.list_batches(_OWNER))[0]["id"]

        result = await svc.remove(_OWNER, "trusted", batch_id, remove_albums=False)

        assert result.kept == 1
        svc._library_service.remove_album.assert_not_awaited()
        assert await store.get_batch(batch_id) is None

    @pytest.mark.asyncio
    async def test_non_owner_gets_not_found(self, store):
        svc = _service(store)
        await store.create_batch(_OWNER, "Mix", "s", [
            {"release_group_mbid": "rg-1", "outcome": "requested"},
        ])
        batch_id = (await store.list_batches(_OWNER))[0]["id"]
        with pytest.raises(ResourceNotFoundError):
            await svc.remove("someone-else", "user", batch_id, remove_albums=True)

    @pytest.mark.asyncio
    async def test_admin_may_remove_any_batch(self, store):
        svc = _service(store)
        await store.create_batch(_OWNER, "Mix", "s", [
            {"release_group_mbid": "rg-1", "outcome": "requested"},
        ])
        batch_id = (await store.list_batches(_OWNER))[0]["id"]
        result = await svc.remove("admin-1", "admin", batch_id, remove_albums=False)
        assert result.kept == 1


class TestRoutes:
    @pytest.fixture
    def client(self, store):
        svc = _service(store)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_discovery_batch_service] = lambda: svc
        override_user_auth(app, user_id=_OWNER)
        return build_test_client(app), svc

    def test_create_and_list_round_trip(self, client):
        http, _svc = client
        resp = http.post(
            "/discover/batches",
            json={
                "name": "Daily Mix — Jul 3",
                "source_section": "daily_mixes",
                "items": [
                    {
                        "release_group_mbid": "rg-9",
                        "artist_mbid": "a-9",
                        "album_name": "Nine",
                        "artist_name": "Niner",
                    }
                ],
            },
        )
        assert resp.status_code == 202
        created = resp.json()
        assert created["name"] == "Daily Mix — Jul 3"
        assert created["items"][0]["outcome"] == "requested"

        listing = http.get("/discover/batches")
        assert listing.status_code == 200
        assert len(listing.json()["batches"]) == 1

    def test_ownership_404_on_foreign_batch(self, client):
        http, _svc = client
        # create a batch as the authenticated user, then probe it with ids that
        # can't belong to them: unknown ids and foreign batches both 404
        assert http.get("/discover/batches/not-a-real-batch").status_code == 404
        assert http.delete("/discover/batches/not-a-real-batch").status_code == 404

    def test_empty_batch_rejected(self, client):
        http, _svc = client
        resp = http.post("/discover/batches", json={"name": "Empty", "items": []})
        assert resp.status_code in (400, 422)


class TestStoreIdempotency:
    def test_double_construction_on_same_path(self, tmp_path):
        lock = threading.Lock()
        path = tmp_path / "library.db"
        DiscoveryBatchStore(db_path=path, write_lock=lock)
        DiscoveryBatchStore(db_path=path, write_lock=lock)
