"""Protocol conformance contract test (contract-test 3a).

``@runtime_checkable`` ``isinstance`` only verifies method NAMES exist; it does
not check parameter signatures or async-ness. This parametrized test runs the
``DownloadClientProtocol`` against TWO implementations - the real
``SlskdRepository`` and the in-memory ``FakeDownloadClient`` - and asserts each
protocol method's signature and async-ness match. Both must pass, proving a
second client requires zero ``services/native`` changes.
"""

import inspect
from pathlib import Path

import httpx
import pytest

from repositories.protocols.download_client import DownloadClientProtocol
from repositories.slskd.slskd_client import SlskdClient
from repositories.slskd.slskd_repository import SlskdRepository
from tests.mocks.fake_download_client import FakeDownloadClient

_PROTO_METHODS = (
    "is_configured",
    "health_check",
    "search_album",
    "search_track",
    "enqueue",
    "get_status",
    "cancel",
    "get_file_path",
    "diagnose_downloads_mount",
)


def _make_slskd_repo() -> SlskdRepository:
    http = httpx.AsyncClient()
    client = SlskdClient(http, "http://slskd", "key")
    return SlskdRepository(
        client=client, url="http://slskd", api_key="key", downloads_mount=Path("/tmp/dl")
    )


def _make_fake_client() -> FakeDownloadClient:
    return FakeDownloadClient()


@pytest.mark.parametrize("factory", [_make_slskd_repo, _make_fake_client])
def test_impl_conforms_to_protocol(factory):
    impl = factory()

    # NAME level (what @runtime_checkable / isinstance gives us).
    assert isinstance(impl, DownloadClientProtocol)
    assert isinstance(impl.client_name, str)
    assert impl.client_name

    # SIGNATURE + async level (the gap isinstance does NOT cover).
    for name in _PROTO_METHODS:
        proto_fn = getattr(DownloadClientProtocol, name)
        impl_fn = getattr(type(impl), name)
        assert inspect.signature(impl_fn) == inspect.signature(proto_fn), name
        assert inspect.iscoroutinefunction(impl_fn) == inspect.iscoroutinefunction(
            proto_fn
        ), name
