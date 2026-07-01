"""msgspec models for the Newznab API.

Modelled on the verified DrunkenSlug (nZEDb) responses captured this session +
the Lidarr/Prowlarr parsers. Newznab is **XML-only** (no JSON path). The release
type itself (``UsenetRelease``) is the indexer boundary type and lives in
``repositories/protocols/indexer.py``; these are the caps/error/usage shapes.
"""

from infrastructure.msgspec_fastapi import AppStruct


class NewznabSubcategory(AppStruct):
    id: int
    name: str = ""


class NewznabCategory(AppStruct):
    id: int
    name: str = ""
    subcats: list[NewznabSubcategory] = []


class NewznabCaps(AppStruct):
    """Parsed ``t=caps``. Drives the query strategy: ``supports_audio_search`` +
    ``audio_search_params`` gate whether we issue structured ``t=music`` or fall
    back to free-text ``t=search`` (DrunkenSlug advertises audio-search=no, so it
    takes the ``t=search`` path). Permissive defaults so a caps fetch failure
    doesn't disable the indexer (matches Lidarr/Prowlarr)."""

    server_title: str | None = None
    server_version: str | None = None
    limit_default: int = 100
    limit_max: int = 100
    supports_text_search: bool = True
    text_search_params: list[str] = []
    supports_audio_search: bool = False
    audio_search_params: list[str] = []
    categories: list[NewznabCategory] = []

    def audio_category_ids(self) -> list[int]:
        """All audio category ids advertised (the ``3000`` parent + its subcats),
        e.g. DrunkenSlug → 3000,3010,3020,3030,3040,3060,3999. Used to validate the
        user's configured categories and to find the (non-standard) Other id."""
        out: list[int] = []
        for cat in self.categories:
            if 3000 <= cat.id < 4000:
                out.append(cat.id)
                out.extend(s.id for s in cat.subcats)
        return out

    def other_audio_category_id(self) -> int | None:
        """The "Audio/Other" id read from caps - 3050 on standard Prowlarr, but
        3999 on nZEDb-derived indexers like DrunkenSlug. Never hardcode it."""
        for cat in self.categories:
            if cat.id == 3000 or cat.name.lower() == "audio":
                for sub in cat.subcats:
                    if sub.name.lower() == "other":
                        return sub.id
        return None


class NewznabApiLimits(AppStruct):
    """``<newznab:apilimits>`` from a search response - the indexer's daily usage
    counters (DrunkenSlug emits ``apiCurrent``/``grabCurrent``). Used to back off
    before hitting a free tier's daily cap. ``*_max`` are often absent."""

    api_current: int | None = None
    api_max: int | None = None
    grab_current: int | None = None
    grab_max: int | None = None


class NewznabError(AppStruct):
    code: int
    description: str = ""
