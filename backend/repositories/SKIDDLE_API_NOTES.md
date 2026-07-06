# Skiddle API - live-verified behavior

Probed 2026-07-06 with a real (owner-held) key. Captured responses:
`tests/fixtures/events/sk_artists.json`, `sk_byartist.json`, `sk_geo.json`.

- **Auth:** `api_key` query param. Every response is HTTP 200 JSON with the
  envelope `{error, totalcount, results}`; failures use `error != 0` (+
  `errormessage`), so the envelope must be checked even on 200. ⚠️ `totalcount`
  is an **int on the artists endpoint but a STRING on the events endpoint**
  (`"392"`) - verified in the 2026-07-06 fixtures.
- **Rate limits:** undocumented daily + hourly caps; no rate headers observed.
  Our limiter stays at 1 req/s.
- **Artist search** (`/artists/?name=…`): ids are STRINGS. ⚠️ Skiddle keeps
  duplicate entries per real act ("Fontaines D.C." id 123568993 AND
  "Fontaines DC" id 123604351, same `spotifyartisturl`) plus near-name tribute
  acts ("Fontaines CD") - resolution must use exact-ish name equality (never
  containment) and collect ALL matching ids.
- **Events by artist** (`/events/search/?a=<artistid>&description=1`): returns
  upcoming events only. Covers UK **and Ireland** (Electric Picnic verified).
  ⚠️ Reading/Leeds festivals appear in BOTH Skiddle and Ticketmaster -
  cross-source dedupe is mandatory.
- **Event shape:** `id` string; `date` = venue-local YYYY-MM-DD; `startdate` =
  ISO datetime; `cancelled` is the STRING `'0'`/`'1'`;
  `cancellationDate`/`rescheduledDate` are empty strings when unset;
  `ticketUrl` may be `''` (fall back to `link`); `venue` carries `name`,
  `town`, `region`, `country` (`'GB'`), float `latitude`/`longitude`;
  `artists[]` (only with `description=1`) carries `artistid`/`name` and is
  often EMPTY for small gigs. Key casing is mixed (`eventname`, `ticketUrl`,
  `EventCode`).
- **Geo search** (`latitude`/`longitude`/`radius`): radius unit is **miles**.
  Not used by the sweep (we filter locally), verified working.
