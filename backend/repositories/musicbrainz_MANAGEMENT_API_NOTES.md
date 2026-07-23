# MusicBrainz Library Management API notes

Verified against the live production JSON API on 2026-07-21. The response `Date`
header was `Tue, 21 Jul 2026`; requests used DroppedNeedle's descriptive user agent.

## Canonical release lookup

The representative request was:

```text
GET /ws/2/release/aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b
    ?fmt=json
    &inc=artist-credits+recordings+release-groups+labels+isrcs+aliases
         +artist-rels+work-rels+recording-rels+recording-level-rels
         +release-group-level-rels+work-level-rels+genres
```

It returned HTTP 200 and the selected Goldberg Variations release. The decoded
surface required by Library Management was present:

- release: `id`, `title`, `status`, `date`, `country`, `barcode`, `asin`,
  `packaging`, `artist-credit`, `label-info`, `media`, `release-group`, `genres`,
  and `relations`;
- release group: `id`, `title`, `first-release-date`, `primary-type`,
  `secondary-types`, credits, aliases, genres, and relations;
- artist credit items: credited `name`, `joinphrase`, and an artist with `id`,
  canonical `name`, `sort-name`, aliases, and genres;
- label info: `catalog-number` plus a nullable label object;
- medium: `id`, numeric `position`, optional `title`, `format`, `track-count`, and
  `tracks`;
- release track: its own `id`, numeric `position`, display `number`, `title`,
  optional `length`, artist credit, and `recording`;
- recording: its distinct `id`, title, length, ISRCs, credits, aliases, genres, and
  relations. Recording relationships included artist/instrument credits and work
  performance links; linked works carried their own relationships.

The response contained 34 tracks and was about 608 KB with all relationship and
genre includes. Production requests must therefore construct the smallest sorted
include set required by the selected profile; the full verification include set is
not a default.

The release-track `track.id` is not the recording MBID. Management must retain both
and must never derive one from the other.

## Missing and malformed identifiers

- A syntactically valid but nonexistent release UUID returned HTTP 404 with JSON
  `{"error":"Not Found", ...}`.
- The all-zero UUID returned HTTP 400 with JSON `{"error":"Invalid mbid.", ...}`.

The repository model must distinguish definitive absence from malformed input and
from transport/provider failure. Tests use sanitized fixtures and never call the live
service.

The existing project-wide MusicBrainz one-request-per-second limiter, priority queue,
retry/circuit-breaker wrapper, and request deduplicator remain authoritative.
