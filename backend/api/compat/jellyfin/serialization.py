"""Jellyfin response encoding + lenient body decoding (04-jellyfin.md s1)."""

from __future__ import annotations

from typing import Any, Type, TypeVar

import msgspec
from fastapi import Request
from fastapi.responses import Response

from core.exceptions import JellyfinError

T = TypeVar("T")


def _strip_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj]
    return obj


def jellyfin_response(payload: Any, *, status: int = 200) -> Response:
    body = _strip_none(msgspec.to_builtins(payload))
    return Response(
        msgspec.json.encode(body), status_code=status, media_type="application/json"
    )


def no_content() -> Response:
    return Response(status_code=204)


def error_response(status: int, body: dict | None) -> Response:
    if body is None:
        return Response(status_code=status)
    return Response(
        msgspec.json.encode(body), status_code=status, media_type="application/json"
    )


async def decode_body(request: Request, model: Type[T]) -> T | None:
    raw = await request.body()
    if not raw:
        return None
    try:
        # lenient: ignore unknown fields so undocumented ones (EventName, Finamp UserId) don't 400
        return msgspec.json.decode(raw, type=model, strict=False)
    except msgspec.ValidationError as exc:
        raise JellyfinError(400, str(exc)) from exc
