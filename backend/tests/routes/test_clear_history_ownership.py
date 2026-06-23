import asyncio
import threading

from fastapi import FastAPI

from api.v1.routes.requests_page import router
from core.dependencies import get_requests_page_service
from infrastructure.persistence.request_history import RequestHistoryStore
from middleware import _get_current_user
from services.native.stubs import LibraryStub
from services.requests_page_service import RequestsPageService
from tests.helpers import build_test_client, mock_user

VALID_MBID = "33333333-3333-3333-3333-333333333333"
OWNER_ID = "owner-user-id"


def _make_service(tmp_path, status: str) -> RequestsPageService:
    store = RequestHistoryStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())

    async def _seed() -> None:
        await store.async_record_request(
            VALID_MBID, "Artist", "Album", user_id=OWNER_ID, initial_status=status,
        )

    asyncio.run(_seed())

    async def _mbids() -> set[str]:
        return set()

    return RequestsPageService(
        library_repo=LibraryStub(),
        request_history=store,
        library_mbids_fn=_mbids,
    )


def _client(tmp_path, *, role: str, user_id: str, status: str = "imported"):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_requests_page_service] = lambda: _make_service(tmp_path, status)
    app.dependency_overrides[_get_current_user] = lambda: mock_user(role=role, user_id=user_id)
    return build_test_client(app)


def test_owner_can_clear_own_history(tmp_path):
    client = _client(tmp_path, role="user", user_id=OWNER_ID)
    resp = client.delete(f"/requests/history/{VALID_MBID}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_non_owner_gets_403(tmp_path):
    client = _client(tmp_path, role="user", user_id="someone-else")
    resp = client.delete(f"/requests/history/{VALID_MBID}")
    assert resp.status_code == 403


def test_non_owner_gets_403_even_when_not_clearable(tmp_path):
    # Ownership is checked before clearability: non-owner gets 403, not 200/False.
    client = _client(tmp_path, role="user", user_id="someone-else", status="downloading")
    resp = client.delete(f"/requests/history/{VALID_MBID}")
    assert resp.status_code == 403


def test_admin_can_clear_any_history(tmp_path):
    client = _client(tmp_path, role="admin", user_id="admin-id")
    resp = client.delete(f"/requests/history/{VALID_MBID}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
