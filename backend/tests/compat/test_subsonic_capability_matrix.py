"""Machine-readable Subsonic capability and dispatch truthfulness."""

import json
from pathlib import Path

from api.compat.subsonic.router import _HANDLERS


def _matrix() -> dict:
    path = (
        Path(__file__).parents[2]
        / "api"
        / "compat"
        / "subsonic"
        / "capability_matrix.json"
    )
    return json.loads(path.read_text())


def test_every_dispatched_endpoint_is_in_capability_matrix():
    matrix = _matrix()
    assert set(_HANDLERS) <= {name.casefold() for name in matrix["endpoints"]}


def test_only_full_extensions_are_advertised():
    matrix = _matrix()
    advertised = matrix["advertised_extensions"]
    extension_states: dict[str, set[str]] = {}
    for entry in matrix["endpoints"].values():
        extension = entry.get("extension")
        if extension:
            name, _version = extension.split(":", 1)
            extension_states.setdefault(name, set()).add(entry["state"])
    assert not (set(advertised) & set(extension_states))


def test_matrix_has_required_evidence_and_deviation_fields():
    matrix = _matrix()
    assert matrix["pinned_open_subsonic_commit"] == "e184c37c3485"
    assert matrix["navidrome_baseline"] == "0.63.2"
    assert matrix["signed_deviations"]
    assert set(matrix["evidence"]) == {
        "open_subsonic",
        "navidrome",
        "automated",
        "real_clients",
    }
