"""Refresh the reviewed Library Management genre asset from MusicBrainz.

Run manually, then review the vocabulary diff. Existing aliases and hierarchy are
retained deliberately because MusicBrainz publishes the canonical names, not our
curated normalization relationships.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = "https://musicbrainz.org/ws/2/genre/all?fmt=txt"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "asset",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "assets"
        / "library_management_genres.json",
    )
    args = parser.parse_args()
    existing = json.loads(args.asset.read_text(encoding="utf-8"))
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": (
                "DroppedNeedle/LibraryManagement "
                "(https://github.com/DroppedNeedle/DroppedNeedle)"
            )
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS URL
        names = sorted(
            {
                line.strip()
                for line in response.read().decode("utf-8").splitlines()
                if line.strip()
            }
        )
    payload = {
        "source": SOURCE_URL,
        "retrieved_at": date.today().isoformat(),
        "source_note": existing["source_note"],
        "genres": names,
        "aliases": existing["aliases"],
        "parents": existing["parents"],
    }
    args.asset.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
