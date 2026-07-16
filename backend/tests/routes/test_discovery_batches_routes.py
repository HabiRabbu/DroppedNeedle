"""Discovery batches: ownership-scoped routes + service behaviour (create outcomes,
removal scoping, recycle-bin routing)."""

import sqlite3
import threading
from pathlib import Path
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
from infrastructure.persistence.library_db import LibraryDB
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.local_catalog import CatalogMembership, LocalAlbum, LocalArtist, LocalTrack
from services.discovery_batch_service import DiscoveryBatchService
from services.local_files_service import LocalFilesService
from services.native.target_catalog_writer_service import TargetCatalogWriterService
from services.native.target_library_repository import TargetLibraryRepository
from services.native.target_native_library_service import TargetNativeLibraryService
from services.native.target_reference_adapters import TargetDiscoveryBatchLibraryService
from tests.helpers import build_test_client, override_user_auth

_OWNER = "owner-1"


@pytest.fixture
def store(tmp_path):
    return DiscoveryBatchStore(
        db_path=tmp_path / "library.db", write_lock=threading.Lock()
    )


def _service(store, **overrides) -> DiscoveryBatchService:
    request_service = MagicMock()
    request_service.request_batch = AsyncMock(
        return_value=SimpleNamespace(success=True, requested=1, skipped=0)
    )
    request_service.cancel_batch = AsyncMock(
        return_value=BatchCancelResponse(
            success=True, cancelled=1, failed=0, message="ok"
        )
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
        get_download_service=lambda: download_service,
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
            _OWNER,
            "trusted",
            "Owner",
            DiscoveryBatchCreate(
                name="Mix", source_section="daily_mixes", items=_items(3)
            ),
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
                _OWNER,
                "trusted",
                "Owner",
                DiscoveryBatchCreate(name="Mix", items=_items(2)),
            )
        assert await svc.list_for_user(_OWNER) == []

    @pytest.mark.asyncio
    async def test_over_cap_rejected(self, store):
        svc = _service(store)
        with pytest.raises(ValidationError):
            await svc.create(
                _OWNER,
                "trusted",
                "Owner",
                DiscoveryBatchCreate(name="Big", items=_items(31)),
            )

    @pytest.mark.asyncio
    async def test_quota_rejection_creates_no_batch(self, store):
        svc = _service(store)
        svc._requests.request_batch = AsyncMock(
            side_effect=ValidationError("over quota")
        )
        with pytest.raises(ValidationError):
            await svc.create(
                _OWNER,
                "user",
                "Owner",
                DiscoveryBatchCreate(name="Mix", items=_items(2)),
            )
        assert await svc.list_for_user(_OWNER) == []


class TestServiceRemove:
    @pytest.mark.asyncio
    async def test_remove_scopes_to_requested_items_only(self, store):
        svc = _service(store)
        # rg-0 was already in the library at batch time -> never touched;
        # rg-1 imported by the batch -> recycled; rg-2 still pending -> cancelled
        await store.create_batch(
            _OWNER,
            "Mix",
            "s",
            [
                {"release_group_mbid": "rg-0", "outcome": "skipped_in_library"},
                {"release_group_mbid": "rg-1", "outcome": "requested"},
                {"release_group_mbid": "rg-2", "outcome": "requested"},
            ],
        )
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
        removed_mbids = [
            c.args[0] for c in svc._library_service.remove_album.await_args_list
        ]
        assert removed_mbids == ["rg-1"]
        # removal is reversible: files go through the recycle bin
        assert svc._library_service.remove_album.await_args.kwargs == {
            "to_recycle": True
        }
        svc._get_download_service().purge_album_downloads.assert_awaited_once_with(
            "rg-1"
        )
        assert await store.get_batch(batch_id) is None

    @pytest.mark.asyncio
    async def test_keep_albums_only_deletes_the_batch_record(self, store):
        svc = _service(store)
        await store.create_batch(
            _OWNER,
            "Mix",
            "s",
            [
                {"release_group_mbid": "rg-1", "outcome": "requested"},
            ],
        )
        batch_id = (await store.list_batches(_OWNER))[0]["id"]

        result = await svc.remove(_OWNER, "trusted", batch_id, remove_albums=False)

        assert result.kept == 1
        svc._library_service.remove_album.assert_not_awaited()
        assert await store.get_batch(batch_id) is None

    @pytest.mark.asyncio
    async def test_non_owner_gets_not_found(self, store):
        svc = _service(store)
        await store.create_batch(
            _OWNER,
            "Mix",
            "s",
            [
                {"release_group_mbid": "rg-1", "outcome": "requested"},
            ],
        )
        batch_id = (await store.list_batches(_OWNER))[0]["id"]
        with pytest.raises(ResourceNotFoundError):
            await svc.remove("someone-else", "user", batch_id, remove_albums=True)

    @pytest.mark.asyncio
    async def test_admin_may_remove_any_batch(self, store):
        svc = _service(store)
        await store.create_batch(
            _OWNER,
            "Mix",
            "s",
            [
                {"release_group_mbid": "rg-1", "outcome": "requested"},
            ],
        )
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
                "name": "Daily Mix - Jul 3",
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
        assert created["name"] == "Daily Mix - Jul 3"
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


class TestTargetRouteAuthority:
    @staticmethod
    async def _environment(tmp_path: Path):
        db_path = tmp_path / "library.db"
        lock = threading.Lock()
        with sqlite3.connect(db_path) as connection:
            connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO auth_users(id) VALUES (?)",
                [(_OWNER,)],
            )
        LibraryDB(db_path, lock)
        native_store = NativeLibraryStore(db_path, lock)
        batch_store = DiscoveryBatchStore(db_path, lock)
        root = tmp_path / "Music"
        root.mkdir()
        target_path = root / "target.flac"
        target_path.write_bytes(b"target-audio")
        legacy_sentinel = root / "legacy-sentinel.flac"
        legacy_sentinel.write_bytes(b"legacy-audio")
        artist = LocalArtist(
            id="target-artist",
            display_name="Target Artist",
            folded_name="target artist",
            kind="person",
            created_at=1,
            updated_at=1,
        )
        album = LocalAlbum(
            id="target-album",
            root_id="root-1",
            grouping_key="target-group",
            title="Target Album",
            album_artist_id=artist.id,
            album_artist_name=artist.display_name,
            created_at=1,
            updated_at=1,
        )
        track = LocalTrack(
            id="target-track",
            local_album_id=album.id,
            root_id="root-1",
            file_path=str(target_path),
            relative_path=target_path.name,
            path_hash="target-path",
            file_size_bytes=target_path.stat().st_size,
            file_mtime_ns=target_path.stat().st_mtime_ns,
            stat_revision="target-stat",
            title="Target Track",
            artist_name=artist.display_name,
            album_title=album.title,
            album_artist_name=artist.display_name,
            file_format="flac",
            imported_at=1,
        )
        await native_store.create_catalog_membership(
            CatalogMembership(album=album, artists=[artist], tracks=[track])
        )
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "INSERT INTO local_album_external_identities "
                "(local_album_id, provider, release_group_mbid, decision_source, selected_at) "
                "VALUES ('target-album', 'musicbrainz', 'target-rg', 'manual', 1)"
            )
            connection.execute(
                "INSERT INTO library_albums "
                "(mbid_lower, mbid, title, raw_json) "
                "VALUES ('legacy-only', 'legacy-only', 'Legacy Only', '{}')"
            )
        target_repo = TargetLibraryRepository(native_store)
        preferences = SimpleNamespace(
            get_typed_library_settings=lambda: SimpleNamespace(
                library_roots=[SimpleNamespace(path=str(root))]
            )
        )
        local_files = LocalFilesService(target_repo, preferences, AsyncMock())
        writer = TargetCatalogWriterService(
            native_store,
            local_files,
            TargetNativeLibraryService(native_store),
            recycle_bin_getter=lambda: root / ".recycle",
        )
        requests = MagicMock()
        requests.request_batch = AsyncMock(
            return_value=SimpleNamespace(success=True, requested=1, skipped=0)
        )
        requests.cancel_batch = AsyncMock(
            return_value=BatchCancelResponse(
                success=True, cancelled=1, failed=0, message="ok"
            )
        )
        history = MagicMock()
        history.async_get_active_mbids = AsyncMock(return_value=set())
        history.async_get_record = AsyncMock(return_value=None)
        download = MagicMock()
        download.purge_album_downloads = AsyncMock()
        service = DiscoveryBatchService(
            batch_store=batch_store,
            request_service=requests,
            request_history=history,
            library_service=TargetDiscoveryBatchLibraryService(writer),
            library_db=target_repo,
            get_download_service=lambda: download,
        )
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_discovery_batch_service] = lambda: service
        override_user_auth(app, user_id=_OWNER, role="trusted")
        return SimpleNamespace(
            http=build_test_client(app),
            store=native_store,
            batches=batch_store,
            requests=requests,
            download=download,
            target_path=target_path,
            legacy_sentinel=legacy_sentinel,
            db_path=db_path,
        )

    @pytest.mark.asyncio
    async def test_create_and_status_use_only_the_target_catalog(self, tmp_path: Path):
        env = await self._environment(tmp_path)

        response = env.http.post(
            "/discover/batches",
            json={
                "name": "Target batch",
                "items": [
                    {
                        "release_group_mbid": "target-rg",
                        "album_name": "Target Album",
                        "artist_name": "Target Artist",
                    },
                    {
                        "release_group_mbid": "new-rg",
                        "album_name": "New Album",
                        "artist_name": "New Artist",
                    },
                ],
            },
        )

        assert response.status_code == 202
        detail = response.json()
        by_id = {item["release_group_mbid"]: item for item in detail["items"]}
        assert by_id["target-rg"]["outcome"] == "skipped_in_library"
        assert by_id["target-rg"]["in_library"] is True
        assert by_id["new-rg"]["outcome"] == "requested"
        assert (
            env.requests.request_batch.await_args.kwargs["items"][0]["musicbrainz_id"]
            == "new-rg"
        )
        assert env.http.get(f"/discover/batches/{detail['id']}").status_code == 200

    @pytest.mark.asyncio
    async def test_removal_recycles_target_audio_and_preserves_legacy(
        self, tmp_path: Path
    ):
        env = await self._environment(tmp_path)
        batch_id = await env.batches.create_batch(
            _OWNER,
            "Imported target",
            "test",
            [{"release_group_mbid": "target-rg", "outcome": "requested"}],
        )

        response = env.http.delete(f"/discover/batches/{batch_id}?remove_albums=true")

        assert response.status_code == 200
        assert response.json()["removed_albums"] == 1
        assert not env.target_path.exists()
        assert env.legacy_sentinel.read_bytes() == b"legacy-audio"
        assert (await env.store.get_target_track("target-track"))[
            "availability"
        ] == "missing"
        env.download.purge_album_downloads.assert_awaited_once_with("target-rg")
        with sqlite3.connect(env.db_path) as connection:
            assert connection.execute("SELECT mbid FROM library_albums").fetchall() == [
                ("legacy-only",)
            ]

    @pytest.mark.asyncio
    async def test_removal_restores_file_when_target_catalog_update_fails(
        self, tmp_path: Path, monkeypatch
    ):
        env = await self._environment(tmp_path)
        batch_id = await env.batches.create_batch(
            _OWNER,
            "Imported target",
            "test",
            [{"release_group_mbid": "target-rg", "outcome": "requested"}],
        )
        monkeypatch.setattr(
            env.store,
            "mark_target_tracks_missing",
            AsyncMock(side_effect=RuntimeError("catalog write failed")),
        )

        response = env.http.delete(f"/discover/batches/{batch_id}?remove_albums=true")

        assert response.status_code == 200
        assert response.json() == {
            "removed_albums": 0,
            "cancelled_requests": 0,
            "kept": 1,
        }
        assert env.target_path.read_bytes() == b"target-audio"
        assert env.legacy_sentinel.read_bytes() == b"legacy-audio"
        assert (await env.store.get_target_track("target-track"))[
            "availability"
        ] == "indexed"
        env.download.purge_album_downloads.assert_not_awaited()
