# Cover Art Archive management API notes

Live-probed on 2026-07-21 against `coverartarchive.org`.

- `GET /release/{release_mbid}` returns an object with an `images` array. Each image
  includes `approved`, `front`, `back`, `comment`, numeric `id`, original `image` URL,
  a `thumbnails` object (observed `250`, `500`, and `1200`), and a `types` array.
- `GET /release-group/{release_group_mbid}` has the same relevant shape. Its images
  come from a representative release and must be labelled release-group fallback,
  never exact-edition artwork.
- Observed image types included `Front`, `Back`, `Spine`, and `Booklet`; one image had
  multiple types (`Back`, `Spine`). Original files may be PNG and must not be assumed
  to be JPEG.
- Response image URLs were observed with an `http` scheme. DroppedNeedle upgrades
  only validated `coverartarchive.org` URLs to HTTPS and rejects every other host.
- A missing entity returns 404. Other non-success responses are provider failures,
  not authoritative empty artwork.

The repository decodes only the fields above into tolerant msgspec structs. This note
records the live provider boundary used by Library Management; tests use a captured,
reduced fixture and never require the live service.
