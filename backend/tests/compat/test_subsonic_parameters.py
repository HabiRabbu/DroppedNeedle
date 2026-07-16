"""Strict and bounded Subsonic query/form parameter decoding."""

import math
import random
import string

import pytest
from starlette.requests import Request

from api.compat.subsonic.parameters import SubsonicParameters, parse_request_parameters
from core.exceptions import SubsonicError


@pytest.mark.parametrize("value", ["", " ", "1.0", "true", "--1", "9" * 21])
def test_integer_rejects_non_integer_and_unbounded_values(value):
    params = SubsonicParameters({"count": [value]})
    with pytest.raises(SubsonicError) as exc:
        params.integer("count")
    assert exc.value.code == 10


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_number_rejects_non_finite_values(value):
    params = SubsonicParameters({"rate": [value]})
    with pytest.raises(SubsonicError):
        params.number("rate")


def test_number_accepts_finite_value_and_bounds():
    params = SubsonicParameters({"rate": ["1.25"]})
    value = params.number("rate", minimum=0.1, maximum=4.0)
    assert value == 1.25
    assert math.isfinite(value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("false", False), ("FALSE", False), ("0", False)],
)
def test_boolean_accepts_only_documented_compatible_spellings(raw, expected):
    assert SubsonicParameters({"flag": [raw]}).boolean("flag", False) is expected


@pytest.mark.parametrize("raw", ["yes", "no", "on", "off", "", "2"])
def test_boolean_rejects_ambiguous_spellings(raw):
    with pytest.raises(SubsonicError):
        SubsonicParameters({"flag": [raw]}).boolean("flag", False)


def test_scalar_rejects_repetition_but_repeatable_preserves_order():
    params = SubsonicParameters({"id": ["one", "two"]})
    with pytest.raises(SubsonicError):
        params.string("id")
    assert params.strings("id") == ["one", "two"]


def test_bounds_and_enum_fail_explicitly():
    with pytest.raises(SubsonicError):
        SubsonicParameters({"count": ["501"]}).integer(
            "count", minimum=0, maximum=500
        )
    with pytest.raises(SubsonicError):
        SubsonicParameters({"type": ["invented"]}).enum(
            "type", {"newest", "recent"}
        )


def test_repeat_and_string_boundaries_are_exact():
    assert len(SubsonicParameters({"id": ["x"] * 500}).strings("id")) == 500
    assert len(SubsonicParameters({"value": ["x" * 4096]}).string("value")) == 4096

    with pytest.raises(SubsonicError):
        SubsonicParameters({"id": ["x"] * 501}).strings("id")
    with pytest.raises(SubsonicError):
        SubsonicParameters({"value": ["x" * 4097]}).string("value")


def test_random_decoder_inputs_always_return_bounded_values_or_protocol_errors():
    rng = random.Random(120)
    alphabet = string.printable + "é音\u0301\x00\x1f"

    for _ in range(1_000):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 80)))
        params = SubsonicParameters({"value": [raw]})
        for decode in (
            lambda: params.integer("value", minimum=-1000, maximum=1000),
            lambda: params.number("value", minimum=-1000.0, maximum=1000.0),
            lambda: params.boolean("value", False),
            lambda: params.enum("value", {"newest", "recent"}),
        ):
            try:
                decoded = decode()
            except SubsonicError as exc:
                assert exc.code == 10
            else:
                assert decoded is not None
                if isinstance(decoded, float):
                    assert math.isfinite(decoded)


def _request(query: bytes = b"", body: bytes = b"") -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    headers = []
    method = "GET"
    if body:
        method = "POST"
        headers = [(b"content-type", b"application/x-www-form-urlencoded")]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/subsonic/rest/ping",
            "query_string": query,
            "headers": headers,
        },
        receive,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [b"value=\xff", b"value=%FF", b"value=%", b"value=%0"])
async def test_request_parser_rejects_invalid_utf8_and_percent_encoding(query):
    with pytest.raises(SubsonicError) as exc:
        await parse_request_parameters(_request(query))
    assert exc.value.code == 10


@pytest.mark.asyncio
async def test_request_parser_preserves_repeated_utf8_values():
    params = await parse_request_parameters(
        _request(b"musicFolderId=one&musicFolderId=%E9%9F%B3")
    )
    assert params == {"musicFolderId": ["one", "音"]}
