"""Normalize cached MusicBrainz data for the target identification pipeline."""

from infrastructure.queue.priority_queue import RequestPriority
from models.identification import AlbumCandidate, CandidateTrack
from repositories.musicbrainz_base import extract_artist_name
from repositories.musicbrainz_repository import MusicBrainzRepository


class MusicBrainzIdentificationRepository:
    def __init__(self, musicbrainz: MusicBrainzRepository) -> None:
        self._musicbrainz = musicbrainz

    async def search_album_candidate_ids(
        self,
        query: str,
        limit: int,
        priority: RequestPriority,
    ) -> list[str]:
        results = await self._musicbrainz.search_albums(
            query,
            limit=limit,
            include_all_types=True,
            priority=priority,
        )
        return [result.musicbrainz_id for result in results if result.musicbrainz_id]

    async def search_recording_candidate_ids(
        self,
        artist: str,
        title: str,
        limit: int,
        priority: RequestPriority,
    ) -> list[str]:
        recordings = await self._musicbrainz.search_recordings(
            artist,
            title,
            limit=limit,
            priority=priority,
        )
        return list(
            dict.fromkeys(
                group.release_group_mbid
                for recording in recordings
                for group in recording.release_groups
                if group.release_group_mbid
            )
        )

    async def get_album_candidate(
        self,
        release_group_mbid: str,
        target_track_count: int,
        priority: RequestPriority,
    ) -> AlbumCandidate | None:
        group = await self._musicbrainz.get_release_group_by_id(
            release_group_mbid,
            includes=["artist-credits", "releases", "media"],
            priority=priority,
        )
        if not group:
            return None
        releases: list[tuple[int, int, str, str]] = []
        for release in group.get("releases") or []:
            release_id = release.get("id")
            if not release_id:
                continue
            track_count = sum(
                int(medium.get("track-count") or 0)
                for medium in release.get("media") or []
            )
            releases.append(
                (
                    abs(track_count - target_track_count) if track_count else 1_000_000,
                    0 if release.get("status") == "Official" else 1,
                    release.get("date") or "9999",
                    release_id,
                )
            )
        if not releases:
            return None
        release_id = min(releases)[3]
        release = await self._musicbrainz.get_release_by_id(
            release_id,
            includes=["recordings", "artist-credits"],
            priority=priority,
        )
        if not release:
            return None
        tracks: list[CandidateTrack] = []
        absolute_position = 0
        for medium_index, medium in enumerate(release.get("media") or [], start=1):
            disc_number = int(medium.get("position") or medium_index)
            for position, track in enumerate(medium.get("tracks") or [], start=1):
                absolute_position += 1
                recording = track.get("recording") or {}
                length_ms = track.get("length") or recording.get("length")
                tracks.append(
                    CandidateTrack(
                        title=track.get("title") or recording.get("title") or "",
                        position=int(track.get("position") or position),
                        disc_number=disc_number,
                        absolute_position=absolute_position,
                        duration_seconds=(
                            float(length_ms) / 1000.0 if length_ms else None
                        ),
                        recording_mbid=recording.get("id") or None,
                        release_track_mbid=track.get("id") or None,
                    )
                )
        credit = group.get("artist-credit") or []
        artist = (credit[0].get("artist") or {}) if credit else {}
        return AlbumCandidate(
            release_group_mbid=release_group_mbid,
            release_mbid=release_id,
            album_title=group.get("title") or "",
            album_artist_name=extract_artist_name(group) or "",
            artist_mbid=artist.get("id") or None,
            tracks=tracks,
            release_type=(group.get("primary-type") or "").casefold() or None,
            secondary_types=[
                value.casefold() for value in (group.get("secondary-types") or [])
            ],
            release_date=release.get("date") or group.get("first-release-date") or None,
        )
