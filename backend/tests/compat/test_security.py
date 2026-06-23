"""T6.2 - compat security: log redaction, CORS, rate limiting, audit log."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from api.compat.common.cors import CompatCORSMiddleware
from api.compat.common.ratelimit import CompatRateLimitMiddleware
from api.compat.common.redact import redacted_path


# ----- redaction (pure) -----

def _req(query: str):
    return SimpleNamespace(url=SimpleNamespace(path="/subsonic/rest/ping", query=query))


def test_redacted_path_masks_secrets():
    out = redacted_path(_req("u=alice&p=sesame&t=abc&s=xy&apiKey=k&c=app"))
    assert "sesame" not in out and "abc" not in out and "k" not in out.split("apiKey=")[1][:3]
    assert "p=%2A%2A%2A" in out or "p=***" in out
    assert "u=alice" in out and "c=app" in out  # non-secrets preserved


def test_redacted_path_no_query():
    assert redacted_path(_req("")) == "/subsonic/rest/ping"


def test_redacted_path_masks_jellyfin_token_and_pw():
    out = redacted_path(_req("Pw=secret&token=tk&api_key=ak"))
    assert "secret" not in out and "tk" not in out and "ak" not in out


# ----- CORS + rate limit (dedicated app) -----

def _app() -> TestClient:
    app = FastAPI()
    app.add_middleware(CompatRateLimitMiddleware)
    app.add_middleware(CompatCORSMiddleware)

    @app.get("/subsonic/rest/ping")
    def ping():
        return {"ok": True}

    @app.post("/jellyfin/Users/AuthenticateByName")
    def auth():
        return {"ok": True}

    @app.get("/jellyfin/Audio/x/stream")
    def stream():
        return Response(b"audio")

    return TestClient(app)


def test_cors_preflight_short_circuits_before_auth():
    client = _app()
    r = client.options("/subsonic/rest/ping")
    assert r.status_code == 204
    assert r.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in r.headers["Access-Control-Allow-Methods"]
    assert "Authorization" in r.headers["Access-Control-Allow-Headers"]


def test_cors_headers_on_normal_response():
    client = _app()
    r = client.get("/subsonic/rest/ping")
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == "*"
    assert "Content-Range" in r.headers["Access-Control-Expose-Headers"]
    # no credentials header with wildcard origin
    assert "Access-Control-Allow-Credentials" not in r.headers


def test_auth_endpoint_strict_bucket_trips():
    client = _app()
    statuses = [client.post("/jellyfin/Users/AuthenticateByName").status_code for _ in range(8)]
    assert 429 in statuses  # strict 2/s cap 5 -> bursts of 8 trip it


def test_streaming_paths_are_exempt():
    client = _app()
    # far more than any browse cap; streaming must never be throttled
    assert all(client.get("/jellyfin/Audio/x/stream").status_code == 200 for _ in range(200))


def test_subsonic_reject_renders_failed_envelope():
    fake = SimpleNamespace(query_params={"f": "json"})
    resp = CompatRateLimitMiddleware._reject(fake, "/subsonic/rest/getArtists")
    body = json.loads(resp.body)["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 0


def test_jellyfin_reject_is_429():
    fake = SimpleNamespace(query_params={})
    resp = CompatRateLimitMiddleware._reject(fake, "/jellyfin/Items")
    assert resp.status_code == 429


# ----- audit log -----

@pytest.mark.asyncio
async def test_create_and_revoke_audit_logged(app_password_service, caplog):
    with caplog.at_level("INFO"):
        record, _secret = await app_password_service.create("user-alice", "Phone")
        await app_password_service.revoke("user-alice", record.id)
    text = caplog.text
    assert "app-password created" in text and "app-password revoked" in text
    # the secret/hash never appears in the audit line
    assert _secret not in text
