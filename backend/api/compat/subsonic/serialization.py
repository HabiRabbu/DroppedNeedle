"""Dual XML/JSON/JSONP subsonic-response serializer (03-subsonic.md s2)."""

from __future__ import annotations

import re
from typing import Any

import msgspec
from fastapi.responses import Response

SUBSONIC_API_VERSION = "1.16.1"
APP_VERSION = "1.0.0"
_NS = "http://subsonic.org/restapi"

# JSONP callback is reflected into JS; restrict to a bare identifier path or drop
# it (fall back to JSON) to prevent reflected-XSS via ?callback=
_CALLBACK_RE = re.compile(r"^[A-Za-z_$][\w$.]{0,127}$")

# C0 controls illegal in XML 1.0 (except tab/newline/CR); file-metadata tag values
# can carry a stray control byte that makes the doc unparseable for strict clients
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _strip_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj]
    return obj


def _xml_escape_text(value: str) -> str:
    value = _INVALID_XML_CHARS.sub("", value)
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _xml_escape_attr(value: str) -> str:
    return _xml_escape_text(value).replace('"', "&quot;")


def _xml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _to_xml(tag: str, value: Any) -> str:
    """builtins node -> XML: dict=element (scalars=attrs, value=text, list=repeated children); list=repeated <tag>; scalar=<tag>text</tag>."""
    if isinstance(value, dict):
        attrs: list[str] = []
        children: list[str] = []
        text = ""
        for k, v in value.items():
            if k == "value":
                text = _xml_escape_text(_xml_scalar(v))
            elif isinstance(v, dict):
                children.append(_to_xml(k, v))
            elif isinstance(v, list):
                children.extend(_to_xml(k, item) for item in v)
            else:
                attrs.append(f' {k}="{_xml_escape_attr(_xml_scalar(v))}"')
        attr_str = "".join(attrs)
        inner = text + "".join(children)
        if inner:
            return f"<{tag}{attr_str}>{inner}</{tag}>"
        return f"<{tag}{attr_str}/>"
    if isinstance(value, list):
        return "".join(_to_xml(tag, item) for item in value)
    return f"<{tag}>{_xml_escape_text(_xml_scalar(value))}</{tag}>"


def _render_xml(body: dict) -> bytes:
    root = _to_xml("subsonic-response", {"xmlns": _NS, **body})
    return ('<?xml version="1.0" encoding="UTF-8"?>' + root).encode("utf-8")


def _emit(body: dict, fmt: str, callback: str | None) -> Response:
    cb = callback if (callback and _CALLBACK_RE.match(callback)) else None
    if fmt == "json" or (fmt == "jsonp" and not cb):
        return Response(
            msgspec.json.encode({"subsonic-response": body}),
            media_type="application/json",
        )
    if fmt == "jsonp":
        payload = msgspec.json.encode({"subsonic-response": body}).decode("utf-8")
        return Response(f"{cb}({payload});", media_type="application/javascript")
    return Response(_render_xml(body), media_type="application/xml")


def _envelope(status: str, server_name: str) -> dict:
    return {
        "status": status,
        "version": SUBSONIC_API_VERSION,
        "type": server_name,
        "serverVersion": APP_VERSION,
        "openSubsonic": True,
    }


def render(
    endpoint_key: str | None,
    payload: Any,
    *,
    fmt: str = "xml",
    callback: str | None = None,
    server_name: str = "DroppedNeedle",
) -> Response:
    body = _envelope("ok", server_name)
    if endpoint_key is not None and payload is not None:
        body[endpoint_key] = msgspec.to_builtins(payload)
    return _emit(_strip_none(body), fmt, callback)


def render_error(
    code: int,
    message: str,
    *,
    fmt: str = "xml",
    callback: str | None = None,
    server_name: str = "DroppedNeedle",
) -> Response:
    body = _envelope("failed", server_name)
    body["error"] = {"code": code, "message": message}
    return _emit(_strip_none(body), fmt, callback)
