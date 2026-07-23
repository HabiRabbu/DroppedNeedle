from typing import Optional
from api.v1.schemas.album import Track


def parse_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    year = date_str.split("-", 1)[0]
    return int(year) if year.isdigit() else None


def find_primary_release(release_group: dict) -> Optional[dict]:
    ranked = get_ranked_releases(release_group)
    return ranked[0] if ranked else None


def get_ranked_releases(release_group: dict) -> list[dict]:
    """Return official releases sorted so digital/mainstream formats come first."""
    releases = release_group.get("releases") or release_group.get("release-list", [])
    official = [r for r in releases if r.get("status") == "Official"]
    if not official:
        official = list(releases)

    def _release_sort_key(r: dict) -> tuple[int, str]:
        country = (r.get("country") or "").upper()
        packaging = (r.get("packaging") or "").lower()
        physical_keywords = {"vinyl", "cassette", "gatefold"}
        if country == "XW":
            rank = 0
        elif any(kw in packaging for kw in physical_keywords):
            rank = 2
        else:
            rank = 1
        return (rank, r.get("id", ""))

    official.sort(key=_release_sort_key)
    return official


def extract_artist_info(release_group: dict) -> tuple[str, str]:
    artist_credit = release_group.get("artist-credit", [])
    artist_name = "Unknown Artist"
    artist_id = ""
    if artist_credit and isinstance(artist_credit, list):
        first_artist = artist_credit[0]
        if isinstance(first_artist, dict):
            artist_obj = first_artist.get("artist", {})
            artist_name = first_artist.get("name") or artist_obj.get(
                "name", "Unknown Artist"
            )
            artist_id = artist_obj.get("id", "")
    return artist_name, artist_id


def extract_tracks(release_data: dict) -> tuple[list[Track], int]:
    tracks = []
    total_length = 0
    medium_list = release_data.get("media") or release_data.get("medium-list", [])
    for medium in medium_list:
        try:
            disc_number = int(medium.get("position") or medium.get("number") or 1)
        except (TypeError, ValueError):
            disc_number = 1
        track_list = medium.get("tracks") or medium.get("track-list", [])
        for track in track_list:
            recording = track.get("recording", {})
            length_ms = track.get("length") or recording.get("length")
            if length_ms:
                try:
                    total_length += int(length_ms)
                except (ValueError, TypeError):
                    pass
            tracks.append(
                Track(
                    position=int(track.get("position") or track.get("number", 0)),
                    disc_number=disc_number,
                    title=recording.get("title") or track.get("title", "Unknown"),
                    length=int(length_ms) if length_ms else None,
                    recording_id=recording.get("id"),
                    release_track_id=track.get("id"),
                )
            )
    return tracks, total_length


def extract_label(release_data: dict) -> Optional[str]:
    label_info_list = release_data.get("label-info") or release_data.get(
        "label-info-list", []
    )
    if label_info_list:
        label_obj = label_info_list[0].get("label")
        if label_obj:
            return label_obj.get("name")
    return None


def build_album_basic_info(
    release_group: dict,
    release_group_id: str,
    artist_name: str,
    artist_id: str,
    in_library: bool,
) -> dict:
    return {
        "title": release_group.get("title", "Unknown Album"),
        "musicbrainz_id": release_group_id,
        "artist_name": artist_name,
        "artist_id": artist_id,
        "release_date": release_group.get("first-release-date"),
        "year": parse_year(release_group.get("first-release-date")),
        "type": release_group.get("primary-type"),
        "disambiguation": release_group.get("disambiguation"),
        "tracks": [],
        "total_tracks": 0,
        "in_library": in_library,
    }


def mb_to_basic_info(
    release_group: dict, release_group_id: str, in_library: bool, is_requested: bool
) -> dict:
    artist_name, artist_id = extract_artist_info(release_group)
    return {
        "title": release_group.get("title", "Unknown Album"),
        "musicbrainz_id": release_group_id,
        "artist_name": artist_name,
        "artist_id": artist_id,
        "release_date": release_group.get("first-release-date"),
        "year": parse_year(release_group.get("first-release-date")),
        "type": release_group.get("primary-type"),
        "disambiguation": release_group.get("disambiguation"),
        "in_library": in_library,
        "requested": is_requested and not in_library,
        "cover_url": None,
    }
