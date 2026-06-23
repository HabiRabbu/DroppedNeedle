# Plex.tv Account API - User Enumeration (AMU-7 verified)

Verified live against a real Plex.tv account on 2026-06-21 (Phase 6, AMU-7). This
file is the source of truth for `PlexRepository.enumerate_users()` and the
`PlexAccount` model. It was written **before** any model or request code, per
AMU-7 ("never assume third-party API shapes - curl/verify against a live server
first, document, then model").

The token used was the Plex **server-owner account token** (`PlexOnlineToken`
from the Plex Media Server `Preferences.xml`). This is the same admin/account
token `PlexRepository._token` is configured with (`get_plex_connection_raw()`),
and the same identity that `plex_user_auth_service` authenticates.

## The join key (the whole game)

The pre-seeded `auth_providers.provider_uid` for an imported Plex user MUST equal
exactly what the live SSO login produces. On login,
`plex_user_auth_service._get_user_profile` reads `account.uuid` from
`get_token_details` and `_find_or_create_user` keys on `profile["uuid"]`
(`plex_user_auth_service.py:99,147,154`).

**Verified:** the account's own `uuid` returned by `GET /api/v2/user` is the
SAME value that appears under the `uuid` field of the enumeration endpoints:

| Endpoint | uuid field | admin uuid matched? |
|----------|------------|---------------------|
| `GET /api/v2/user` (the account itself) | JSON `uuid` | n/a (source of truth) |
| `GET /api/home/users` | XML attribute `uuid` | yes |
| `GET /api/v2/home/users` | JSON `uuid` | yes |

So **`uuid` is the join key** (a hex string, e.g. `962867…`). The numeric `id`
(e.g. `748897044`) is NOT sufficient and must not be used as `provider_uid`.

## Endpoints probed (live, redacted)

All probed with headers: `X-Plex-Token`, `X-Plex-Client-Identifier`,
`X-Plex-Product: DroppedNeedle`, `X-Plex-Version: 1.0`, `Accept: application/json`.

### `GET https://plex.tv/api/v2/user` -> 200, `application/json`
The authenticated account. Confirms the `uuid` field name and that the token is
an account token. Fields include: `id`, `uuid`, `username`, `title`, `email`,
`friendlyName`, `thumb`, `home`, `homeAdmin`, `authToken`, ...
```json
{"id":748897044,"uuid":"962867[..hex..]","username":"harvey1463",
 "title":"harvey1463","email":"<email>","friendlyName":"",
 "thumb":"https://plex.tv/users/962867[..hex..]/avatar?c=...","authToken":"<tok>", ...}
```

### `GET https://plex.tv/api/home/users` -> 200, `application/xml` (LEGACY)
`Accept: application/json` is IGNORED here - returns XML. `<MediaContainer>` with
`<User>` children. Each `<User>` carries `id`, `uuid`, `admin`, `guest`,
`restricted`, `hasPassword`, `protected`, `title`, `username`, `email`, `thumb`.
```xml
<MediaContainer friendlyName="myPlex" ... size="1">
  <User id="748897044" uuid="962867[..hex..]" admin="1" guest="0" restricted="0"
        hasPassword="true" protected="0" title="harvey1463" username="harvey1463"
        email="<email>" thumb="https://plex.tv/users/962867[..hex..]/avatar?c=..."/>
</MediaContainer>
```

### `GET https://plex.tv/api/v2/home/users` -> 200, `application/json` (PREFERRED)
JSON variant of Home/managed users. Top-level `{subscription, users:[...]}`.
Each user entry keys: `id`, `uuid`, `title`, `username`, `email`, `friendlyName`,
`thumb`, `hasPassword`, `restricted`, `updatedAt`, `restrictionProfile`, `admin`,
`guest`, `protected`, `subscription`.
```json
{"subscription":false,"users":[
  {"id":748897044,"uuid":"962867[..hex..]","title":"harvey1463",
   "username":"harvey1463","email":"<email>","friendlyName":null,
   "thumb":"https://plex.tv/users/962867[..hex..]/avatar?c=...","admin":true,
   "restricted":false,"guest":false,"protected":false, ...}]}
```

### `GET https://plex.tv/api/users` -> 200, `application/xml` (LEGACY friends)
Shared friends. This account has 0 friends -> empty container.
```xml
<MediaContainer friendlyName="myPlex" ... totalSize="0" size="0"></MediaContainer>
```

### `GET https://plex.tv/api/v2/friends` -> 200, `application/json` (PREFERRED friends)
JSON variant of shared friends. Returns a bare JSON **list**. This account has 0
friends -> `[]`.
```json
[]
```

## Decisions for the implementation

1. **Use the v2 JSON endpoints** (`/api/v2/home/users` and `/api/v2/friends`).
   They return real JSON (verified), so no XML parser is needed - simpler and
   exactly matches the verified shape. The legacy XML endpoints are documented
   above for completeness but are not used.
2. **Home + friends are two separate calls** and must be **merged + de-duplicated
   by `uuid`** (a Home admin could in principle also be a friend; de-dup is cheap
   and required by the phase doc).
3. **`PlexAccount` fields** (the verified subset we need): `uuid` (join key),
   `username`, `title`, `email: str | None`, `thumb: str | None`,
   `source: "home" | "friend"`.
4. **Home payload** is an object `{"users": [...]}`; **friends payload** is a bare
   list `[...]`. The parser handles both (dict-with-`users` OR bare list).

## Verified gap (AMU-7 honesty)

The probed account has **no shared friends**, so the `/api/v2/friends` *entry*
shape could not be observed directly (only the empty list `[]` was verified). The
parser models friend entries with the SAME verified v2 user schema as
`/api/v2/home/users` (`uuid`/`username`/`title`/`email`/`thumb` - field names
that are consistent across `/api/v2/user`, `/api/v2/home/users`). To stay safe if
a real friends payload ever differs: `parse_plex_account` reads every field via
`.get()` and **returns `None` (skips the entry) when `uuid` is missing**, so a
shape mismatch degrades to "friend not listed" rather than a wrong `provider_uid`
that would silently create a second account on login. If you later have shared
friends, re-run the probe and confirm the entry carries `uuid`.
