"""Source-scoped quarantine/identity keys (D8).

The generalised ``download_quarantine`` table keys a blocklisted release by
``(source, identity, release_group_mbid)`` where ``identity`` is a single opaque
string whose encoding is source-specific. Centralised here so the store, the
scorers, and the orchestrator agree byte-for-byte on what a row's key means.

- **soulseek** identity = ``username`` + ``filename`` - preserves exactly the
  old ``(username, filename)`` semantics, so Phase 0 is behaviour-preserving.
- **usenet** identity = normalised ``title`` + size-rounded-to-MB (D8/m4): the
  cross-indexer release identity, NOT the per-indexer ``guid``.
"""

import re

SOURCE_SOULSEEK = "soulseek"
SOURCE_USENET = "usenet"

_UNIT = "\x1f"  # ASCII unit separator - never appears in a username/filename/title
_WS = re.compile(r"\s+")


def soulseek_identity(username: str, filename: str) -> str:
    """Identity of a soulseek per-file pick - the old quarantine key, encoded."""
    return f"{username}{_UNIT}{filename}"


def usenet_identity(title: str, size_bytes: int) -> str:
    """Identity of a Usenet release: normalised title + size-rounded-to-MB.

    Title is lower-cased with whitespace collapsed so trivial spacing/case
    differences across indexers dedup together; size is bucketed to the MB so a
    byte or two of metadata jitter between indexers doesn't split the identity
    (mirrors the cross-indexer dedup key, ``02-…`` §Aggregation)."""
    norm = _WS.sub(" ", title.strip().lower())
    size_mb = size_bytes // (1024 * 1024)
    return f"{norm}{_UNIT}{size_mb}"
