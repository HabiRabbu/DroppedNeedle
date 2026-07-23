# LRCLIB API notes

Verified against `https://lrclib.net` on 2026-07-22.

- `GET /api/get` accepts `track_name`, `artist_name`, `album_name`, and integer
  `duration`. It does not accept a MusicBrainz identifier as an exact lookup key.
- A successful exact lookup returned an object with numeric `id` and `duration`,
  string `trackName`, `artistName`, and `albumName`, boolean `instrumental`, and
  nullable string `plainLyrics` and `syncedLyrics` values.
- A missing exact lookup returned HTTP 404 with `statusCode`, `name`, and `message`.
- `GET /api/search` returned an array with multiple plausible candidates for a common
  recording. Library Management therefore never promotes a search result
  automatically; only `/api/get` can feed automatic or manual-run projections.
- The successful response did not advertise a numeric rate-limit header, and the
  public documentation did not publish a numeric request allowance. DroppedNeedle
  applies a conservative one-request-per-second local ceiling and honors HTTP 429
  `Retry-After` without presenting that ceiling as provider policy.

The recorded live payload is represented by the independent fixture under
`tests/fixtures/lrclib/`. Lyrics text is intentionally omitted from the fixture; the
shape, nullable fields, and length-independent behavior are what the adapter tests.
