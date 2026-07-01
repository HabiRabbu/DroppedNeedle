"""PreferencesService Newznab indexers (D6): per-element key mask/preserve/encrypt,
upsert by id, delete, reorder, priority ordering."""

import json
from pathlib import Path

import pytest

from api.v1.schemas.settings import INDEXER_API_KEY_MASK, NewznabIndexerSettings
from core.config import Settings
from services.preferences_service import PreferencesService


@pytest.fixture
def prefs(tmp_path: Path) -> PreferencesService:
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    return PreferencesService(settings)


def test_empty_by_default(prefs):
    assert prefs.get_indexers() == []
    assert prefs.get_indexers_raw() == []


def test_create_assigns_id_and_encrypts_key(prefs):
    iid = prefs.save_indexer(
        NewznabIndexerSettings(name="DS", url="https://idx.test/api", api_key="secret")
    )
    assert iid  # a fresh uuid was minted
    stored = json.loads(prefs._config_path.read_text())["indexers"][0]["api_key"]
    assert stored not in ("", "secret")  # ciphertext at rest


def test_key_masked_on_read_decrypted_raw(prefs):
    iid = prefs.save_indexer(
        NewznabIndexerSettings(name="DS", url="https://idx.test/api", api_key="secret")
    )
    assert prefs.get_indexers()[0].api_key == INDEXER_API_KEY_MASK
    raw = next(i for i in prefs.get_indexers_raw() if i.id == iid)
    assert raw.api_key == "secret"


def test_pasted_whitespace_stripped_from_key_and_url(prefs):
    # A real DrunkenSlug 403: a key pasted with a leading space + tab reached the indexer
    # verbatim. Both save and raw-read must yield the clean key (and clean url).
    iid = prefs.save_indexer(
        NewznabIndexerSettings(name="DS", url="  https://idx.test/api  ", api_key=" \tsecret\n")
    )
    raw = next(i for i in prefs.get_indexers_raw() if i.id == iid)
    assert raw.api_key == "secret"
    assert raw.url == "https://idx.test/api"


def test_masked_save_preserves_key_per_element(prefs):
    iid = prefs.save_indexer(
        NewznabIndexerSettings(name="DS", url="https://idx.test/api", api_key="secret")
    )
    # Re-save the same indexer with the masked sentinel + a changed name.
    prefs.save_indexer(
        NewznabIndexerSettings(id=iid, name="DS-renamed", url="https://idx.test/api", api_key=INDEXER_API_KEY_MASK)
    )
    raw = next(i for i in prefs.get_indexers_raw() if i.id == iid)
    assert raw.api_key == "secret"  # preserved
    assert raw.name == "DS-renamed"  # updated


def test_upsert_updates_existing_not_duplicates(prefs):
    iid = prefs.save_indexer(NewznabIndexerSettings(name="A", url="https://a.test/api", api_key="k"))
    prefs.save_indexer(NewznabIndexerSettings(id=iid, name="A2", url="https://a.test/api", api_key="k"))
    indexers = prefs.get_indexers()
    assert len(indexers) == 1
    assert indexers[0].name == "A2"


def test_delete_removes_indexer(prefs):
    iid = prefs.save_indexer(NewznabIndexerSettings(name="A", url="https://a.test/api"))
    prefs.delete_indexer(iid)
    assert prefs.get_indexers() == []


def test_reorder_sets_priority_and_orders(prefs):
    a = prefs.save_indexer(NewznabIndexerSettings(name="A", url="https://a.test/api", priority=1))
    b = prefs.save_indexer(NewznabIndexerSettings(name="B", url="https://b.test/api", priority=2))
    prefs.reorder_indexers([b, a])  # drag B above A
    ordered = prefs.get_indexers()
    assert [i.name for i in ordered] == ["B", "A"]
    assert ordered[0].priority < ordered[1].priority


def test_default_categories_applied(prefs):
    prefs.save_indexer(NewznabIndexerSettings(name="A", url="https://a.test/api"))
    assert prefs.get_indexers()[0].categories == [3000, 3010, 3040]


def test_url_normalised_to_https(prefs):
    prefs.save_indexer(NewznabIndexerSettings(name="A", url="idx.test/api/"))
    assert prefs.get_indexers()[0].url == "https://idx.test/api"
