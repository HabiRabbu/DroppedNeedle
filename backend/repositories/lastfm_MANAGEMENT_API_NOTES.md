# Last.fm Library Management API notes

Verified against the configured production API key on 2026-07-22.

`album.getTopTags` was called for Radiohead's _The Bends_ with `autocorrect=0`.
`artist.getTopTags` was called for Radiohead with `autocorrect=0`. Both returned HTTP
200 JSON with one `toptags` object. Its `tag` member was a list of 10 objects; every
observed object contained string `name`, integer `count`, and string `url` fields.
Album and artist counts were integer weights from 0 through 100. The surrounding
`@attr` object is intentionally ignored by the management decoder.

The successful wire contract is represented by tolerant repository-local msgspec
structs in `lastfm_management_models.py`. The repository projects those values into
provider-neutral `GenreCandidate` objects before they leave the repository. Album and
artist results use separate bounded cache keys under the established `lfm_` prefix and
the existing process-wide 5/s Last.fm limiter.

A missing API key remains a configuration failure for this optional source. The
previous live invalid-key probe returned HTTP 403 with error 10. Last.fm's official
method pages document error 29 as rate limiting, but deliberately provoking it would
violate the project's verified limiter and could disrupt the shared host. The existing
JSON error envelope is therefore decoded into `RateLimitedError` from the documented
code and covered with an executable mock response rather than abusive live traffic.

Genre projection prefers album weights and then artist weights according to profile
source order. The configurable minimum weight and canonical whitelist gate apply
before any tag can become managed metadata. Missing configuration, transport failure,
decode failure, or rate limiting marks Last.fm deferred and preserves existing genres;
it never becomes an authoritative empty list.
