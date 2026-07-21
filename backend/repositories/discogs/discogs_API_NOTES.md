# Discogs API notes

Verified live on 2026-07-21 with DroppedNeedle 2.3.0's descriptive user agent.

## Operations used

- `GET https://api.discogs.com/releases/249504` returned HTTP 200 without
  authentication. The modeled response fields were `id`, `master_id`, `title`,
  `artists_sort`, `artists`, `year`, `country`, `released`, `labels`, `formats`,
  `identifiers`, `tracklist`, `uri`, and `resource_url`.
- `GET https://api.discogs.com/database/search?type=release&artist=Nirvana&release_title=Nevermind&per_page=3`
  returned HTTP 200 without authentication. The modeled result fields were `id`,
  `master_id`, `title`, `year`, `country`, `label`, `catno`, `format`, `formats`,
  `barcode`, `uri`, and `resource_url`.
- Both responses advertised `x-discogs-ratelimit: 25`. DroppedNeedle therefore limits
  this unauthenticated adapter to 25 requests per minute with no burst.

The live payloads also contained image, community, and marketplace-adjacent fields.
Those fields are intentionally absent from the wire and normalized models and never
cross the repository boundary.

## Terms reviewed

The official Discogs API Terms of Use were read during implementation, immediately
before the dev rollout, and during the pre-push audit on 2026-07-21. The page was still
last updated on 2025-05-27. This workflow uses only contribution metadata covered as
core music data, does not use images, user/collection, community, or marketplace data,
links displayed data to its exact Discogs release, and never displays a fetched provider
value after six hours without a refresh.
