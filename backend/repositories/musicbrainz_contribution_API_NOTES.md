# MusicBrainz contribution API notes

Verified against the official production service and documentation on 2026-07-21 with
DroppedNeedle 2.3.0's descriptive user agent.

## URL resolution

- `GET /ws/2/url?resource=https://www.discogs.com/release/3562468&inc=release-rels&fmt=json`
  returned one `release` relation, release MBID
  `aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b`. The relationship UUID was
  `4a78823c-1c53-4176-a5f3-58026c76f2bc`.
- `GET /ws/2/url?resource=https://www.discogs.com/master/261784&inc=release-group-rels&fmt=json`
  returned one `release_group` relation, release-group MBID
  `dcff25f1-702d-3b5e-b0da-d48172e6e62a`. The relationship UUID was
  `99e550f3-5ab4-3110-b5b9-fe01d970b126`.
- A slugged form of the same Discogs release URL returned HTTP 404. Resolution therefore
  uses the fixed numeric URL form, never a pasted or provider slug.
- A missing URL returns HTTP 404; the shared API wrapper normalizes that to an empty
  typed resolution. The relation list is retained in full so a multi-target response is
  represented as ambiguity rather than selecting its first item.

The official web-service documentation still permits text URL lookups with `resource`
and relation includes. The shared one-request-per-second MusicBrainz limiter remains in
force.

## Release verification and duplicate search

- `GET /ws/2/release/aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b` with
  `inc=artist-credits+labels+recordings+release-groups+url-rels` returned the expected
  release, release-group, artist-credit, label-info, media, track, recording, and URL
  relationship objects. Optional release fields included barcode, country, date,
  packaging, and status.
- `GET /ws/2/release?query=release:"Discovery" AND artist:"Daft Punk"&limit=2` returned
  the documented `{count, created, offset, releases}` envelope. Search releases included
  score plus the release, artist-credit, release-group, label, event, and media summaries
  accepted by the tolerant contribution models.
- These production shapes were re-probed on 2026-07-21. Sanitized response subsets are
  kept in offline fixtures; tests do not call the live service.

## Release editor seeding

The official release-editor seeding documentation still specifies a POST to
`https://musicbrainz.org/release/add`, ordered/repeated release, event, label, artist
credit, medium, track, URL, edit-note, and `redirect_uri` fields. A successful submission
adds `release_mbid` to the redirect URI. An anonymous live GET to `/release/add` returned
the MusicBrainz login page, confirming that sign-in and submission remain on
MusicBrainz.

The Discogs release URL relationship has UUID
`4a78823c-1c53-4176-a5f3-58026c76f2bc`; the release editor's numeric seed link type is
`76`. Both are covered by fixtures and were re-verified before the dev rollout.

The official seeding documentation was re-read on 2026-07-21. Verified artist credits
use `artist_credit.names.x.mbid`; an existing release group uses `release_group`.
