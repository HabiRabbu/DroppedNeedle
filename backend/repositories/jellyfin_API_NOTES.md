# Jellyfin management refresh API notes

Live verification performed on 2026-07-22 against the configured DroppedNeedle
development Jellyfin server, version 10.11.11. Credentials and the server URL are
intentionally omitted.

The server's own `/api-docs/openapi.json` documents:

- `POST /Library/Refresh` starts a library scan and returns `204 No Content`.
- The route can also return `401`, `403`, or `503`; `503` may include
  `Retry-After`.
- `POST /Library/Media/Updated` accepts a `MediaUpdateInfoDto` whose `Updates`
  entries contain `Path` and an `UpdateType` of `Created`, `Modified`, or
  `Deleted`.

The configured server's `/Library/VirtualFolders` response contained three media
folders. None of their locations exactly matched a DroppedNeedle native library
root. Targeted path notifications would therefore rely on an unverified path
translation and are unsafe. DroppedNeedle uses the verified global
`POST /Library/Refresh` route instead.

A live authenticated call to `POST /Library/Refresh` returned `204` with an empty
body. The repository treats only that verified success shape as successful.
