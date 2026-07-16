"""Provider-independent grouping and stable local-album continuity."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from models.identification import (
    ExistingAlbumMembership,
    GroupingTrack,
    ProposedLocalAlbum,
)

_DISC_DIRECTORY = re.compile(r"^(?:cd|disc|disk)[\s._-]*0*(\d+)$", re.IGNORECASE)
_SPACE = re.compile(r"\s+")


def normalize_group_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return _SPACE.sub(" ", normalized).casefold()


def _display_consensus(values: list[str], fallback: str) -> str:
    usable = [value.strip() for value in values if value.strip()]
    if not usable:
        return fallback
    folded_counts = Counter(normalize_group_value(value) for value in usable)
    selected = min(
        folded_counts,
        key=lambda value: (-folded_counts[value], value),
    )
    return min(value for value in usable if normalize_group_value(value) == selected)


def _directory_context(track: GroupingTrack) -> tuple[str, str | None]:
    parent = PurePosixPath(track.relative_path).parent
    match = _DISC_DIRECTORY.match(parent.name)
    if match and str(parent.parent) not in ("", "."):
        return str(parent.parent), match.group(1)
    return (str(parent) if str(parent) else "."), None


def grouping_directory(relative_path: str) -> str:
    parent = PurePosixPath(relative_path).parent
    if _DISC_DIRECTORY.match(parent.name) and str(parent.parent) not in ("", "."):
        return str(parent.parent)
    return str(parent) if str(parent) else "."


def _hungarian_min(cost: list[list[int]]) -> list[int]:
    size = len(cost)
    if size == 0:
        return []
    u = [0] * (size + 1)
    v = [0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    infinity = 10**18
    for row in range(1, size + 1):
        p[0] = row
        column = 0
        minimum = [infinity] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[column] = True
            source = p[column]
            delta = infinity
            next_column = 0
            for candidate_column in range(1, size + 1):
                if used[candidate_column]:
                    continue
                candidate = (
                    cost[source - 1][candidate_column - 1]
                    - u[source]
                    - v[candidate_column]
                )
                if candidate < minimum[candidate_column]:
                    minimum[candidate_column] = candidate
                    way[candidate_column] = column
                if minimum[candidate_column] < delta:
                    delta = minimum[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(size + 1):
                if used[candidate_column]:
                    u[p[candidate_column]] += delta
                    v[candidate_column] -= delta
                else:
                    minimum[candidate_column] -= delta
            column = next_column
            if p[column] == 0:
                break
        while column:
            previous = way[column]
            p[column] = p[previous]
            column = previous
    assignment = [0] * size
    for column in range(1, size + 1):
        if p[column]:
            assignment[p[column] - 1] = column - 1
    return assignment


def assign_album_continuity(
    existing: list[ExistingAlbumMembership],
    proposed: list[ProposedLocalAlbum],
) -> list[ProposedLocalAlbum]:
    """Choose the maximum-total-overlap one-to-one continuity assignment."""
    ordered_existing = sorted(
        existing, key=lambda album: (album.created_at, album.local_album_id)
    )
    ordered_proposed = sorted(proposed, key=lambda album: album.grouping_key)
    if not ordered_proposed:
        return []

    track_to_existing: dict[str, list[int]] = defaultdict(list)
    for row, album in enumerate(ordered_existing):
        for track_id in album.track_ids:
            track_to_existing[track_id].append(row)
    overlaps: Counter[tuple[int, int]] = Counter()
    existing_edges: dict[int, set[int]] = defaultdict(set)
    proposed_edges: dict[int, set[int]] = defaultdict(set)
    for column, album in enumerate(ordered_proposed):
        for track_id in album.track_ids:
            for row in track_to_existing.get(track_id, []):
                overlaps[(row, column)] += 1
                existing_edges[row].add(column)
                proposed_edges[column].add(row)

    retained: dict[str, tuple[str, str]] = {}
    visited_existing: set[int] = set()
    for initial in sorted(existing_edges):
        if initial in visited_existing:
            continue
        component_existing: set[int] = set()
        component_proposed: set[int] = set()
        pending_existing = [initial]
        while pending_existing:
            row = pending_existing.pop()
            if row in component_existing:
                continue
            component_existing.add(row)
            for column in existing_edges[row]:
                if column in component_proposed:
                    continue
                component_proposed.add(column)
                pending_existing.extend(proposed_edges[column] - component_existing)
        visited_existing.update(component_existing)
        rows = sorted(component_existing)
        columns = sorted(component_proposed)
        size = max(len(rows), len(columns))
        maximum = max(
            overlaps[(row, column)] for row in rows for column in existing_edges[row]
        )
        weights = [
            [
                overlaps[(rows[row], columns[column])]
                if row < len(rows) and column < len(columns)
                else 0
                for column in range(size)
            ]
            for row in range(size)
        ]
        assignment = _hungarian_min(
            [
                [maximum - weights[row][column] for column in range(size)]
                for row in range(size)
            ]
        )
        for component_row, component_column in enumerate(assignment[: len(rows)]):
            if component_column >= len(columns):
                continue
            row = rows[component_row]
            column = columns[component_column]
            value = overlaps[(row, column)]
            if value == 0:
                continue
            old = ordered_existing[row]
            new = ordered_proposed[column]
            old_best = max(
                overlaps[(row, candidate)] for candidate in existing_edges[row]
            )
            new_best = max(
                overlaps[(candidate, column)] for candidate in proposed_edges[column]
            )
            tied = (
                sum(
                    overlaps[(row, candidate)] == old_best
                    for candidate in existing_edges[row]
                )
                > 1
                or sum(
                    overlaps[(candidate, column)] == new_best
                    for candidate in proposed_edges[column]
                )
                > 1
            )
            retained[new.grouping_key] = (
                old.local_album_id,
                "CONTINUITY_TIE_BROKEN" if tied else "MAXIMUM_TRACK_OVERLAP",
            )
    return [
        ProposedLocalAlbum(
            grouping_key=album.grouping_key,
            title=album.title,
            album_artist_name=album.album_artist_name,
            track_ids=album.track_ids,
            reason_code=album.reason_code,
            retained_album_id=(retained.get(album.grouping_key) or (None, None))[0],
            continuity_reason_code=(retained.get(album.grouping_key) or (None, None))[
                1
            ],
        )
        for album in proposed
    ]


class LocalAlbumGrouper:
    """Create conservative local groups without consulting a provider."""

    def group(
        self,
        tracks: list[GroupingTrack],
        *,
        existing: list[ExistingAlbumMembership] | None = None,
    ) -> list[ProposedLocalAlbum]:
        groups: dict[tuple[str, str, str], list[GroupingTrack]] = defaultdict(list)
        reasons: dict[tuple[str, str, str], str] = {}

        for track in sorted(tracks, key=lambda item: item.relative_path):
            if track.membership_locked and track.current_album_id:
                key = ("manual", track.current_album_id, "")
                groups[key].append(track)
                reasons[key] = "MANUAL_MEMBERSHIP_RESTORED"
                continue
            directory, disc = _directory_context(track)
            album = normalize_group_value(track.album_title)
            album_artist = normalize_group_value(track.album_artist_name)
            if album:
                artist_partition = "" if track.is_compilation else album_artist
                key = (directory, album, artist_partition)
                groups[key].append(track)
                reasons[key] = (
                    "COMPATIBLE_DISC_DIRECTORIES"
                    if disc is not None
                    else "CONSISTENT_ALBUM_TAGS"
                )
            else:
                key = (directory, "", "")
                groups[key].append(track)
                reasons[key] = "MISSING_ALBUM_TAGS"

        expanded: list[tuple[tuple[str, str, str], list[GroupingTrack], str]] = []
        for key, members in sorted(groups.items()):
            if key[1] or key[0] == "manual":
                expanded.append((key, members, reasons[key]))
                continue
            directory_tagged = [
                (candidate_key, candidate_members)
                for candidate_key, candidate_members in groups.items()
                if candidate_key[0] == key[0] and candidate_key[1]
            ]
            if len(directory_tagged) == 1:
                target_key, target_members = directory_tagged[0]
                numbered = all(member.track_number > 0 for member in members)
                occupied = {
                    member.track_number
                    for member in target_members
                    if member.track_number
                }
                if numbered and not any(
                    member.track_number in occupied for member in members
                ):
                    target_members.extend(members)
                    continue
            for member in members:
                single_key = (key[0], f"untagged:{member.local_track_id}", "")
                expanded.append((single_key, [member], "AMBIGUOUS_FALLBACK_GROUP"))

        proposed: list[ProposedLocalAlbum] = []
        seen_keys: Counter[str] = Counter()
        for key, members, reason in expanded:
            directory = key[1] if key[0] == "manual" else key[0]
            title = _display_consensus(
                [member.album_title for member in members],
                PurePosixPath(directory).name or "Unknown Album",
            )
            artist = _display_consensus(
                [member.album_artist_name for member in members], "Unknown Artist"
            )
            base_key = f"{members[0].root_id}:{directory}:{normalize_group_value(title)}:{normalize_group_value(artist)}"
            seen_keys[base_key] += 1
            grouping_key = (
                base_key
                if seen_keys[base_key] == 1
                else f"{base_key}:{seen_keys[base_key]}"
            )
            proposed.append(
                ProposedLocalAlbum(
                    grouping_key=grouping_key,
                    title=title,
                    album_artist_name=artist,
                    track_ids=sorted(member.local_track_id for member in members),
                    reason_code=reason,
                )
            )
        return assign_album_continuity(existing or [], proposed)
