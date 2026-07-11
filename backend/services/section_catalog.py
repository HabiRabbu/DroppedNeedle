"""Canonical catalog of user-toggleable Home/Discover sections.

Single source of truth for section keys, display metadata, service
requirements, and the response fields each key controls. The settings UI
renders this catalog; the home/discover routes use it to blank disabled
sections out of the (shared, fully-built) cached response at read time.
"""

from typing import Any, Literal

import msgspec

from infrastructure.serialization import clone_with_updates

Page = Literal["home", "discover", "sidebar"]

# 'listenbrainz'/'lastfm' are per-user links; 'library' is the global library.
Requires = Literal["listenbrainz", "lastfm", "library"] | None


class SectionDef(msgspec.Struct, frozen=True):
    key: str
    title: str
    description: str
    zone: str
    requires: Requires = None
    # Response fields blanked when the section is disabled. Empty for
    # client-only chrome (the frontend filters those itself).
    fields: tuple[str, ...] = ()


HOME_SECTIONS: tuple[SectionDef, ...] = (
    SectionDef(
        key="trending_artists",
        title="Trending Artists",
        description="Artists trending across your music source right now.",
        zone="What's Hot",
        fields=("trending_artists",),
    ),
    SectionDef(
        key="popular_albums",
        title="Popular Now",
        description="Albums popular across your music source this week.",
        zone="What's Hot",
        fields=("popular_albums",),
    ),
    SectionDef(
        key="weekly_exploration",
        title="Weekly Exploration",
        description="Your ListenBrainz weekly exploration playlist.",
        zone="For You",
        requires="listenbrainz",
        fields=("weekly_exploration",),
    ),
    SectionDef(
        key="your_top_albums",
        title="Your Top Albums",
        description="What you personally played most this month.",
        zone="For You",
        fields=("your_top_albums",),
    ),
    SectionDef(
        key="recently_played",
        title="Recently Played",
        description="Your latest plays in DroppedNeedle.",
        zone="For You",
        fields=("recently_played",),
    ),
    SectionDef(
        key="recently_added",
        title="Recently Added",
        description="The newest imports in your library.",
        zone="For You",
        requires="library",
        fields=("recently_added",),
    ),
    SectionDef(
        key="favorite_artists",
        title="Favorite Artists",
        description="Artists from your loved tracks.",
        zone="Your Library",
        fields=("favorite_artists",),
    ),
    SectionDef(
        key="library_artists",
        title="Library Artists",
        description="A shelf of artists from your library.",
        zone="Your Library",
        requires="library",
        fields=("library_artists",),
    ),
    SectionDef(
        key="library_albums",
        title="Library Albums",
        description="A shelf of albums from your library.",
        zone="Your Library",
        requires="library",
        fields=("library_albums",),
    ),
    SectionDef(
        key="genre_list",
        title="Browse Genres",
        description="Genre tiles built from your library.",
        zone="Browse Genres",
        requires="library",
        fields=("genre_list", "genre_artists", "genre_artist_images"),
    ),
)

DISCOVER_SECTIONS: tuple[SectionDef, ...] = (
    SectionDef(
        key="discover_queue",
        title="Discover Queue",
        description="A personalised album-by-album discovery deck.",
        zone="Essentials",
        fields=("discover_queue_enabled",),
    ),
    SectionDef(
        key="playlist_discovery",
        title="Discover for a Playlist",
        description="Album suggestions seeded from any playlist.",
        zone="Essentials",
        fields=(),  # client-only chrome
    ),
    SectionDef(
        key="listeners_like_you",
        title="Listening Lounge",
        description="Browse albums picked for you by ear - tap a cover to hear it.",
        zone="Essentials",
        fields=("listeners_like_you",),
    ),
    SectionDef(
        key="daily_mixes",
        title="Daily Mixes",
        description="Genre-clustered mixes of new and familiar albums.",
        zone="Made For You",
        requires="library",
        fields=("daily_mixes",),
    ),
    SectionDef(
        key="radio_sections",
        title="Radio Stations",
        description="Album radios seeded by your top artists.",
        zone="Made For You",
        fields=("radio_sections",),
    ),
    SectionDef(
        key="because_you_listen_to",
        title="Because You Listened",
        description="Artists similar to the ones you play most.",
        zone="Because You Listened",
        fields=("because_you_listen_to",),
    ),
    SectionDef(
        key="artists_you_might_like",
        title="Artists You Might Like",
        description="A wider net of similar artists.",
        zone="Because You Listened",
        fields=("artists_you_might_like",),
    ),
    SectionDef(
        key="popular_in_your_genres",
        title="Popular in Your Genres",
        description="Big names in the genres you listen to.",
        zone="Because You Listened",
        fields=("popular_in_your_genres",),
    ),
    SectionDef(
        key="fresh_releases",
        title="Fresh Releases",
        description="New releases picked for you by ListenBrainz.",
        zone="New & Fresh",
        requires="listenbrainz",
        fields=("fresh_releases",),
    ),
    SectionDef(
        key="top_picks",
        title="Top Picks for You",
        description="Albums we think you'd like, scored against your taste.",
        zone="New & Fresh",
        fields=("top_picks",),
    ),
    SectionDef(
        key="new_from_followed",
        title="New From Artists You Follow",
        description="Fresh releases from your followed artists.",
        zone="New & Fresh",
        fields=("new_from_followed",),
    ),
    SectionDef(
        key="missing_essentials",
        title="Missing Essentials",
        description="Celebrated albums missing from artists you collect.",
        zone="New & Fresh",
        requires="library",
        fields=("missing_essentials",),
    ),
    SectionDef(
        key="weekly_exploration",
        title="Weekly Exploration",
        description="Your ListenBrainz weekly exploration playlist.",
        zone="New & Fresh",
        requires="listenbrainz",
        fields=("weekly_exploration",),
    ),
    SectionDef(
        key="anniversaries",
        title="Milestone Anniversaries",
        description="Library albums turning 10, 20, 30… this year.",
        zone="From Your Library",
        requires="library",
        fields=("anniversaries",),
    ),
    SectionDef(
        key="rediscover",
        title="Rediscover",
        description="Library albums you haven't played in a while.",
        zone="From Your Library",
        fields=("rediscover",),
    ),
    SectionDef(
        key="lastfm_recent_scrobbles",
        title="Recent Scrobbles",
        description="Your latest Last.fm scrobbles.",
        zone="From Your Library",
        requires="lastfm",
        fields=("lastfm_recent_scrobbles",),
    ),
    SectionDef(
        key="unexplored_genres",
        title="Unexplored Genres",
        description="Genres adjacent to your taste you haven't dug into.",
        zone="Browse Genres",
        fields=("unexplored_genres",),
    ),
    SectionDef(
        key="genre_list",
        title="Browse Genres",
        description="Genre tiles built from your library.",
        zone="Browse Genres",
        requires="library",
        fields=("genre_list", "genre_artist_images"),
    ),
    SectionDef(
        key="globally_trending",
        title="Globally Trending",
        description="Artists trending worldwide.",
        zone="Trending Now",
        fields=("globally_trending",),
    ),
    SectionDef(
        key="lastfm_weekly_artist_chart",
        title="Last.fm Weekly Artists",
        description="Your Last.fm weekly artist chart.",
        zone="Trending Now",
        requires="lastfm",
        fields=("lastfm_weekly_artist_chart",),
    ),
    SectionDef(
        key="lastfm_weekly_album_chart",
        title="Last.fm Weekly Albums",
        description="Your Last.fm weekly album chart.",
        zone="Trending Now",
        requires="lastfm",
        fields=("lastfm_weekly_album_chart",),
    ),
)

# Sidebar service entries (issue #52). Hiding one hides both its library link
# and its admin "Connect X" hint. All client-only chrome: the frontend filters.
SIDEBAR_SECTIONS: tuple[SectionDef, ...] = (
    SectionDef(
        key="youtube",
        title="YouTube",
        description="The YouTube entry in the sidebar.",
        zone="Services",
    ),
    SectionDef(
        key="jellyfin",
        title="Jellyfin",
        description="The Jellyfin entry in the sidebar.",
        zone="Services",
    ),
    SectionDef(
        key="navidrome",
        title="Navidrome",
        description="The Navidrome entry in the sidebar.",
        zone="Services",
    ),
    SectionDef(
        key="plex",
        title="Plex",
        description="The Plex entry in the sidebar.",
        zone="Services",
    ),
    SectionDef(
        key="localfiles",
        title="Local Files",
        description="The Local Files entry in the sidebar.",
        zone="Services",
    ),
)

_CATALOGS: dict[str, tuple[SectionDef, ...]] = {
    "home": HOME_SECTIONS,
    "discover": DISCOVER_SECTIONS,
    "sidebar": SIDEBAR_SECTIONS,
}

# Blank values per response field. List-typed fields must blank to [] and the
# queue flag to False; everything else is an Optional section that blanks to None.
_FIELD_BLANKS: dict[str, Any] = {
    "because_you_listen_to": [],
    "daily_mixes": [],
    "radio_sections": [],
    "genre_artists": {},
    "genre_artist_images": {},
    "discover_queue_enabled": False,
}


def sections_for(page: Page) -> tuple[SectionDef, ...]:
    return _CATALOGS[page]


def valid_keys(page: Page) -> set[str]:
    return {s.key for s in _CATALOGS[page]}


def apply_section_prefs(response: Any, page: Page, disabled_keys: set[str]) -> Any:
    """Blank every disabled section's fields out of a built response."""
    if not disabled_keys:
        return response
    updates: dict[str, Any] = {}
    for section in _CATALOGS[page]:
        if section.key not in disabled_keys:
            continue
        for field in section.fields:
            updates[field] = _FIELD_BLANKS.get(field)
    if not updates:
        return response
    return clone_with_updates(response, updates)
