"""Strict, bounded decoding for Subsonic query and form parameters."""

from __future__ import annotations

import json
import math
import re
from urllib.parse import parse_qsl

from fastapi import Request

from core.exceptions import SubsonicError

MAX_REQUEST_PARAMETER_BYTES = 64 * 1024
MAX_PARAMETER_COUNT = 1024
MAX_PARAMETER_KEY_LENGTH = 128
MAX_PARAMETER_VALUE_LENGTH = 8192
MAX_REPEAT_COUNT = 500
MAX_STRING_LENGTH = 4096
_INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")
_TRUE = frozenset({"true", "1"})
_FALSE = frozenset({"false", "0"})
_MALFORMED_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _invalid(name: str) -> SubsonicError:
    return SubsonicError(10, f"Invalid parameter '{name}'")


def _decode_pairs(value: bytes) -> list[tuple[str, str]]:
    try:
        decoded = value.decode("utf-8")
        if _MALFORMED_PERCENT.search(decoded):
            raise ValueError("malformed percent escape")
        return list(
            parse_qsl(
                decoded,
                keep_blank_values=True,
                encoding="utf-8",
                errors="strict",
            )
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise SubsonicError(10, "Invalid request parameter encoding") from exc


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


async def parse_request_parameters(
    request: Request, *, json_fields: frozenset[str] = frozenset()
) -> dict[str, list[str]]:
    query = request.scope.get("query_string", b"")
    if len(query) > MAX_REQUEST_PARAMETER_BYTES:
        raise SubsonicError(10, "Request parameters are too large")
    pairs = _decode_pairs(query)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if request.method == "POST" and content_type == "application/x-www-form-urlencoded":
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_REQUEST_PARAMETER_BYTES):
            raise SubsonicError(10, "Request parameters are too large")
        body = await request.body()
        if len(body) > MAX_REQUEST_PARAMETER_BYTES:
            raise SubsonicError(10, "Request parameters are too large")
        pairs.extend(_decode_pairs(body))
    elif request.method == "POST" and content_type == "application/json" and json_fields:
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_REQUEST_PARAMETER_BYTES):
            raise SubsonicError(10, "Request parameters are too large")
        body = await request.body()
        if len(body) > MAX_REQUEST_PARAMETER_BYTES:
            raise SubsonicError(10, "Request parameters are too large")
        try:
            value = json.loads(body, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise SubsonicError(10, "Invalid JSON request body") from exc
        if not isinstance(value, dict) or any(key not in json_fields for key in value):
            raise SubsonicError(10, "Invalid JSON request body")
        for key, item in value.items():
            if isinstance(item, bool):
                pairs.append((key, "true" if item else "false"))
            elif isinstance(item, (str, int, float)) and not isinstance(item, complex):
                pairs.append((key, str(item)))
            else:
                raise _invalid(key)
    if len(pairs) > MAX_PARAMETER_COUNT:
        raise SubsonicError(10, "Too many request parameters")
    params: dict[str, list[str]] = {}
    for key, value in pairs:
        if not key or len(key) > MAX_PARAMETER_KEY_LENGTH:
            raise SubsonicError(10, "Invalid parameter name")
        if len(value) > MAX_PARAMETER_VALUE_LENGTH:
            raise _invalid(key)
        params.setdefault(key, []).append(value)
    return params


class SubsonicParameters:
    def __init__(self, values: dict[str, list[str]]) -> None:
        self.values = values

    def string(
        self,
        name: str,
        default: str | None = None,
        *,
        max_length: int = MAX_STRING_LENGTH,
    ) -> str | None:
        values = self.values.get(name, [])
        if not values:
            return default
        if len(values) != 1 or len(values[0]) > max_length:
            raise _invalid(name)
        return values[0]

    def strings(
        self,
        name: str,
        *,
        max_count: int = MAX_REPEAT_COUNT,
        max_length: int = MAX_STRING_LENGTH,
    ) -> list[str]:
        values = self.values.get(name, [])
        if len(values) > max_count or any(len(value) > max_length for value in values):
            raise _invalid(name)
        return values

    def integer(
        self,
        name: str,
        default: int | None = None,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int | None:
        raw = self.string(name)
        if raw is None:
            return default
        if not raw or len(raw) > 20 or _INTEGER_RE.fullmatch(raw) is None:
            raise _invalid(name)
        value = int(raw)
        if minimum is not None and value < minimum:
            raise _invalid(name)
        if maximum is not None and value > maximum:
            raise _invalid(name)
        return value

    def number(
        self,
        name: str,
        default: float | None = None,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float | None:
        raw = self.string(name)
        if raw is None:
            return default
        if not raw or len(raw) > 64:
            raise _invalid(name)
        try:
            value = float(raw)
        except ValueError as exc:
            raise _invalid(name) from exc
        if not math.isfinite(value):
            raise _invalid(name)
        if minimum is not None and value < minimum:
            raise _invalid(name)
        if maximum is not None and value > maximum:
            raise _invalid(name)
        return value

    def boolean(self, name: str, default: bool) -> bool:
        raw = self.string(name)
        if raw is None:
            return default
        normalized = raw.casefold()
        if normalized in _TRUE:
            return True
        if normalized in _FALSE:
            return False
        raise _invalid(name)

    def enum(
        self, name: str, allowed: set[str] | frozenset[str], default: str | None = None
    ) -> str | None:
        value = self.string(name)
        if value is None:
            return default
        if value not in allowed:
            raise _invalid(name)
        return value
