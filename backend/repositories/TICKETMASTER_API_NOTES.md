# Ticketmaster Discovery v2 - live-verified behavior

Probed 2026-07-06 with a real (owner-held) consumer key. Captured responses:
`tests/fixtures/events/tm_attr.json`, `tests/fixtures/events/tm_events.json`.

- **Auth:** `apikey=<Consumer Key>` query param on every call. The Consumer
  *Secret* is not used by the Discovery API at all.
- **Quota:** response headers `rate-limit: 5000`, `rate-limit-available`,
  `rate-limit-reset` (epoch **milliseconds**) confirm 5,000 calls/day. The docs
  state both "5 req/s" and "2 req/s" in different places - our limiter encodes
  the 2/s floor.
- **Attraction search** (`/attractions.json?keyword=…&classificationName=Music`):
  attractions carry a dynamic `externalLinks` map; `externalLinks.musicbrainz`
  is a list of `{id, url}` whose `id` is a MusicBrainz artist MBID (verified:
  Fontaines D.C. → `fd87acc7-…`, the correct MB entity). ⚠️ Sibling attractions
  exist ("Fontaines D.C. DJ Set", no MBID) - resolution must prefer the
  MBID-confirmed attraction and never accept phrase containment alone.
- **Events by attraction** (`/events.json?attractionId=…&sort=date,asc`):
  worldwide results in one call (no countryCode needed). Venue objects carry
  `city.name`, `country.countryCode`, and `location.{latitude,longitude}` as
  **strings**; `state.name` is often absent. Dates: `dates.start.localDate`
  (venue-local) + optional `dateTime`; `dates.status.code` (`onsale`, `offsale`,
  `cancelled`, `rescheduled`, …). `url` is market-localized
  (ticketmaster.co.uk for GB events). `_embedded` is OMITTED entirely on empty
  result sets. Festival events embed the full lineup as attractions, each with
  its own optional MBID.
- **Pagination:** `page` object (`size`, `totalElements`, `totalPages`,
  `number`); we fetch `size=200` and follow page numbers up to 3 pages,
  logging truncation. Docs cap deep paging at size×page ≤ ~1000.
- **Coverage:** US, CA, GB, IE + AT/BE/CH/CZ/DE/DK/ES/FI/FR/IT/NL/NO/PL/SE and
  more (per Discovery Feed docs). Geo search near Liverpool returned 177 music
  events incl. small venues.
