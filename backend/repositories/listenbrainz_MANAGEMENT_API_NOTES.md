# ListenBrainz Library Management API notes

Verified against the live production API and current official server source on
2026-07-21. No user token was required for these metadata reads.

## Release-group metadata

The supported call is GET only:

```text
GET /1/metadata/release_group/
    ?release_group_mbids=<comma-separated MBIDs>
    &inc=artist%20tag%20release
```

A one-ID and a two-ID request both returned HTTP 200. The top-level object is keyed
by release-group MBID. An entry can contain:

- `artist`: `artist_credit_id`, display `name`, and ordered `artists`; artist items
  include `artist_mbid`, `name`, `join_phrase`, and optional descriptive fields;
- `release_group`: an object with `caa_id`, `caa_release_mbid`, `date`, `name`,
  `rels`, and `type`;
- `release`: an object with the same summary shape, not a list;
- `tag`: an object with `artist` and `release_group` arrays. Tag items contain
  `tag`, integer `count`, and an optional `genre_mbid`; artist tag items also carry
  `artist_mbid`.

Curated genre entries carry `genre_mbid`; ordinary folksonomy entries may omit it.

## Batching and errors

- A valid missing MBID returned HTTP 200 with `{}`.
- An invalid MBID returned HTTP 400 with
  `{"code":400,"error":"Release group mbid not-a-uuid is not valid."}`.
- POST to the release-group endpoint returned HTTP 405 with an HTML body and
  `Allow: GET, HEAD, OPTIONS`. The recording metadata endpoint's POST support must
  not be generalized to release groups.
- Live responses exposed `X-RateLimit-Limit: 30` and related remaining/reset headers.
  This does not authorize raising DroppedNeedle's existing verified 5/s limiter.

The current server route accepts comma-separated GET IDs but does not apply its
generic `MAX_ITEMS_PER_GET` guard to this endpoint. DroppedNeedle therefore uses an
explicit 25-ID batch ceiling to bound URL and response sizes. This is a local safety
bound, not an upstream claim. `Retry-After` and `X-RateLimit-*` remain response hints.

Tests use sanitized fixtures and never call the live service.
