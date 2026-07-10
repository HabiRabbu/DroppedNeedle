"""Guardrail 1: DroppedNeedle ships no source that indexes infringing content.

The user supplies every *acquisition* source the app can reach - their own slskd
instance, or their own Newznab indexers and their own SABnzbd. No indexer, tracker,
or P2P server is preset, bundled, recommended, or curated in-tree.

Free Music (D24) is the one deliberate exception, and it is the exception that
proves the rule: it ships archive.org preset and enabled by default, and it offers
only items carrying an explicit Creative Commons or public-domain licence. Bundling
a lawful source is not the thing this guardrail exists to prevent. Bundling
specialised means of *finding infringing content* is. The tests below pin both
halves: no forbidden domain anywhere, and Free Music still filtered to open
licences against archive.org.

This is the load-bearing distinction between an automation tool and an index, and
the README's "Legality boundary" section asserts it in prose. It held until now
because we remembered it. This test makes CI remember instead.

Scope: shipped source only. ``backend/tests/`` is exempt because the Newznab
mock in ``tests/mocks/`` is the executable record of live-verified indexer
behaviour and is *named after* the real services it was captured from - that is
the house pattern for stateful integrations, not a bundled source.
"""

from pathlib import Path

import pytest

from api.v1.schemas.settings import NewznabIndexerSettings
from repositories import archive_repository as archive

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent

# Domains of public indexers, trackers, and the Soulseek servers themselves.
#
# We match *domains*, not bare service names, for two reasons. A shipped source
# is a reachable address; a docstring naming the indexers a parser was verified
# against (``routes/indexers.py``) is the opposite - it is the house rule on
# recording what you probed live. And bare names collide: "abnzb" is a substring
# of "sabnzbd".
_FORBIDDEN_DOMAINS = (
    # Usenet indexers
    "nzbgeek.info",
    "nzbplanet.net",
    "drunkenslug.com",
    "nzbfinder.ws",
    "omgwtfnzbs.org",
    "dognzb.cr",
    "usenet-crawler.com",
    "tabula-rasa.pw",
    "ninjacentral.co.za",
    "althub.co.za",
    "nzb.su",
    # Torrent trackers
    "thepiratebay.org",
    "rarbg.to",
    "1337x.to",
    "torrentleech.org",
    "iptorrents.com",
    "redacted.ch",
    "orpheus.network",
    "nyaa.si",
    # Soulseek network servers (we speak to slskd over HTTP, never to these)
    "slsknet.org",
)

# A subdomain (``api.nzbgeek.info``) carries its parent domain as a substring, so
# plain containment catches those too.

_SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".svelte-kit", "build", "dist"}


def _shipped_sources() -> list[Path]:
    """Every source file that ends up in a release, excluding tests."""
    files: list[Path] = []

    for path in _BACKEND.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if "tests" in path.parts:
            continue
        files.append(path)

    frontend_src = _REPO / "frontend" / "src"
    for pattern in ("*.ts", "*.svelte"):
        for path in frontend_src.rglob(pattern):
            if any(part in _SKIP_DIRS or part == "__tests__" for part in path.parts):
                continue
            # Covers `*.svelte.spec.ts` too.
            if path.name.endswith(".spec.ts"):
                continue
            files.append(path)

    return files


def test_no_indexer_or_tracker_domain_in_shipped_source():
    """No source the user did not configure is reachable from a stock install."""
    offenders: list[str] = []

    for path in _shipped_sources():
        haystack = path.read_text(encoding="utf-8", errors="ignore").lower()
        for domain in _FORBIDDEN_DOMAINS:
            if domain in haystack:
                offenders.append(f"{path.relative_to(_REPO)}: {domain!r}")

    assert offenders == [], (
        "Guardrail 1 broken: shipped source carries the address of a source the user "
        "did not configure. DroppedNeedle must ship no indexers, trackers, or sources.\n  "
        + "\n  ".join(offenders)
    )


def test_newznab_indexer_settings_ship_empty():
    """A freshly constructed indexer carries no preset endpoint or credential.

    A default url or api_key here would let a stock install reach a source nobody
    chose, whatever the README says.
    """
    indexer = NewznabIndexerSettings()

    assert indexer.id == ""
    assert indexer.name == ""
    assert indexer.url == ""
    assert indexer.api_key == ""


def test_the_one_bundled_source_is_archive_org():
    """Free Music is allowed to be preset because of what it points at. If it ever
    points somewhere else, that is a legal decision, not a refactor."""
    for url in (archive.SEARCH_URL, archive.METADATA_URL, archive.DOWNLOAD_URL):
        assert url.startswith("https://archive.org/"), url


def test_the_bundled_source_offers_only_open_licences():
    """The licence filter is what keeps Free Music lawful. Widening it to accept an
    all-rights-reserved item turns the one bundled source into a bundled infringement
    tool, so it is pinned here rather than left to the repository's own tests."""
    for allowed in (
        "http://creativecommons.org/licenses/by-nc-sa/3.0/",
        "https://creativecommons.org/licenses/by/4.0/",
        "http://creativecommons.org/publicdomain/zero/1.0/",
        "https://creativecommons.org/publicdomain/mark/1.0/",
    ):
        assert archive.is_open_licence(allowed), allowed

    for refused in (
        None,
        "",
        "   ",
        "all rights reserved",
        "http://example.com/licenses/by/4.0/",
        # a lookalike host, and a licence named but not linked
        "https://creativecommons.org.evil.test/licenses/by/4.0/",
        "CC BY-NC-SA 3.0",
    ):
        assert not archive.is_open_licence(refused), refused


def test_the_bundled_source_search_demands_a_licence():
    """A search that did not require licenceurl would return all-rights-reserved
    items for the ranker to pick from."""
    source = (_BACKEND / "repositories" / "archive_repository.py").read_text(encoding="utf-8")
    assert "licenseurl:[* TO *]" in source


def test_no_indexers_are_preconfigured_in_the_example_config():
    """The legacy example config predates the current runtime shape, but it is
    still shipped, still read by humans, and must not seed a source."""
    example = _REPO / "config" / "config.example.json"
    if not example.exists():
        pytest.skip("config.example.json has been removed")

    body = example.read_text(encoding="utf-8", errors="ignore").lower()
    for domain in _FORBIDDEN_DOMAINS:
        assert domain not in body, f"config.example.json seeds a source: {domain!r}"
