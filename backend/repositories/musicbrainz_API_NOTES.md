# MusicBrainz API notes

Verified against the live MusicBrainz JSON API on 2026-07-20 with
`inc=releases+release-groups` on recording lookups.

- Each `releases` item carried `id`, `status`, and `date`.
- Its `release-group` object carried `id`, `title`, `primary-type`,
  `secondary-types`, and `first-release-date`.
- Recording `7ab031d9-a864-48fa-ae91-8b936ccbaaa1` returned Official releases
  in the Compilation release group `edc167ea-ca3e-4178-9f2e-f43d62b19380`.
- Recording `a3d03e85-f63a-431e-bd03-71598f2faddd` returned a Bootleg release
  in the Live release group `65f14827-0b2d-4ed1-81a1-75ceae8d6543`.

The fields remain optional in local models because MusicBrainz linked-entity
payloads can be sparse. Ranking must not substitute one recording MBID for
another; it only chooses among release groups already attached to that recording.
