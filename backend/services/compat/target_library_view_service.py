"""Target-only neutral library projection backed solely by NativeLibraryStore."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from services.compat.view_models import ViewAlbum, ViewArtist, ViewGenre, ViewTrack

if TYPE_CHECKING:
    from infrastructure.persistence.auth_store import UserRecord
    from infrastructure.persistence.native_library_store import NativeLibraryStore
    from services.compat.favorites_service import FavoritesService
    from services.native.target_reference_adapters import TargetPlayHistoryStore


def _dominant_genre(rows: list[dict]) -> str | None:
    counts = Counter(row.get("genre") for row in rows if row.get("genre"))
    return counts.most_common(1)[0][0] if counts else None


class TargetLibraryViewService:
    def __init__(
        self,
        store: "NativeLibraryStore",
        favorites_service: "FavoritesService",
        play_history_store: "TargetPlayHistoryStore | None" = None,
    ) -> None:
        self._store = store
        self._favorites = favorites_service
        self._history = play_history_store

    async def get_library_revision(self) -> int:
        return await self._store.get_catalog_revision()

    async def missing_targets(
        self, targets: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        by_kind = {
            kind: [item_id for item_kind, item_id in targets if item_kind == kind]
            for kind in ("artist", "album", "track")
        }
        existing = await self._store.target_existing_ids(
            artist_ids=by_kind["artist"],
            album_ids=by_kind["album"],
            track_ids=by_kind["track"],
        )
        return [target for target in targets if target[1] not in existing[target[0]]]

    async def get_artists(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "name",
        sort_order: str = "asc",
        q: str | None = None,
        user: "UserRecord | None" = None,
    ) -> tuple[list[ViewArtist], int]:
        del sort_by
        rows, total = await self._store.list_target_artists(
            limit=limit,
            offset=offset,
            search=q,
            sort_order=sort_order,
        )
        artists = [self._artist(row) for row in rows]
        await self._overlay_favorites(artists, "artist", user)
        await self._overlay_plays(artists, "artist", user)
        return artists, total

    async def get_albums(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        sort: str = "recent",
        q: str | None = None,
        file_format: str | None = None,
        decade: int | None = None,
        user: "UserRecord | None" = None,
    ) -> tuple[list[ViewAlbum], int]:
        del file_format
        return await self.get_albums_offset(
            limit=page_size,
            offset=max(0, page - 1) * page_size,
            sort=sort,
            q=q,
            from_year=decade,
            to_year=decade + 9 if decade is not None else None,
            user=user,
        )

    async def get_albums_offset(
        self,
        *,
        limit: int,
        offset: int,
        sort: str = "recent",
        q: str | None = None,
        from_year: int | None = None,
        to_year: int | None = None,
        genre: str | None = None,
        user: "UserRecord | None" = None,
    ) -> tuple[list[ViewAlbum], int]:
        rows, total = await self._store.list_target_albums(
            limit=limit,
            offset=offset,
            sort=sort,
            search=q,
            from_year=from_year,
            to_year=to_year,
            genre=genre,
        )
        albums = [self._album(row) for row in rows]
        await self._overlay_favorites(albums, "album", user)
        await self._overlay_plays(albums, "album", user)
        return albums, total

    async def get_albums_by_ids(
        self, album_ids: list[str], *, user: "UserRecord | None" = None
    ) -> list[ViewAlbum]:
        requested = list(dict.fromkeys(album_ids))
        if not requested:
            return []
        rows, _ = await self._store.list_target_albums(
            limit=len(requested), offset=0, sort="name", album_ids=requested
        )
        by_id = {row["release_group_mbid"]: self._album(row) for row in rows}
        resolved = await self._store.resolve_target_ids("album", requested)
        albums = [
            by_id[resolved[identifier]]
            for identifier in requested
            if resolved.get(identifier) in by_id
        ]
        await self._overlay_favorites(albums, "album", user)
        await self._overlay_plays(albums, "album", user)
        return albums

    async def get_starred_albums(
        self, user: "UserRecord", *, limit: int, offset: int
    ) -> list[ViewAlbum]:
        favorites = await self._favorites.list(user.id, "album")
        return await self.get_albums_by_ids(
            [item_id for item_id, _ in favorites[offset : offset + limit]], user=user
        )

    async def get_albums_for_artist(
        self, artist_id: str, *, user: "UserRecord | None" = None
    ) -> list[ViewAlbum]:
        rows, _ = await self._store.list_target_albums(
            limit=10_000,
            offset=0,
            sort="name",
            artist_id=artist_id,
        )
        albums = [self._album(row) for row in rows]
        await self._overlay_favorites(albums, "album", user)
        await self._overlay_plays(albums, "album", user)
        return albums

    async def get_artist_with_albums(
        self, artist_id: str, *, user: "UserRecord | None" = None
    ) -> tuple[ViewArtist, list[ViewAlbum]] | None:
        resolved = await self._store.resolve_target_id("artist", artist_id)
        if resolved is None:
            return None
        rows, _ = await self._store.list_target_artists(
            limit=1, offset=0, sort_order="asc", artist_ids=[resolved]
        )
        if not rows:
            return None
        albums = await self.get_albums_for_artist(resolved, user=user)
        if not albums:
            return None
        artist = self._artist(rows[0])
        await self._overlay_favorites([artist], "artist", user)
        await self._overlay_plays([artist], "artist", user)
        return artist, albums

    async def get_album(
        self, album_id: str, *, user: "UserRecord | None" = None
    ) -> ViewAlbum | None:
        rows = await self._store.get_target_album_tracks(album_id)
        if not rows:
            return None
        album = self._album_from_tracks(rows)
        await self._overlay_favorites([album], "album", user)
        await self._overlay_plays([album], "album", user)
        return album

    async def get_album_tracks(
        self, album_id: str, *, user: "UserRecord | None" = None
    ) -> list[ViewTrack]:
        return await self.tracks_from_rows(
            await self._store.get_target_album_tracks(album_id), user=user
        )

    async def get_track(
        self, file_id: str, *, user: "UserRecord | None" = None
    ) -> ViewTrack | None:
        row = await self._store.get_target_track(file_id)
        if row is None or row["availability"] != "indexed":
            return None
        tracks = await self.tracks_from_rows([row], user=user)
        return tracks[0]

    async def get_tracks_by_file_ids(
        self, file_ids: list[str], *, user: "UserRecord | None" = None
    ) -> dict[str, ViewTrack]:
        rows = await self._store.get_target_tracks_by_ids(file_ids)
        tracks = await self.tracks_from_rows(
            [rows[file_id] for file_id in file_ids if file_id in rows], user=user
        )
        return {track.file_id: track for track in tracks}

    async def get_tracks_page(
        self,
        *,
        limit: int = 48,
        offset: int = 0,
        sort: str = "recent",
        q: str | None = None,
        user: "UserRecord | None" = None,
    ) -> tuple[list[ViewTrack], int]:
        del sort
        rows, total = await self._store.list_target_tracks(
            limit=limit, offset=offset, search=q
        )
        return await self.tracks_from_rows(rows, user=user), total

    async def get_genres(self) -> list[ViewGenre]:
        return [
            ViewGenre(
                name=row["genre"],
                song_count=int(row["song_count"]),
                album_count=int(row["album_count"]),
            )
            for row in await self._store.list_target_genres()
        ]

    async def get_songs_by_genre(
        self,
        genre: str,
        *,
        limit: int = 50,
        offset: int = 0,
        user: "UserRecord | None" = None,
    ) -> list[ViewTrack]:
        rows, _ = await self._store.list_target_tracks(
            limit=limit, offset=offset, genre=genre
        )
        return await self.tracks_from_rows(rows, user=user)

    async def get_tracks_by_artist_mbids(
        self,
        mbids: list[str],
        *,
        user: "UserRecord | None" = None,
        limit: int = 500,
    ) -> list[ViewTrack]:
        rows, _ = await self._store.list_target_tracks(
            limit=limit, offset=0, artist_ids=mbids
        )
        return await self.tracks_from_rows(rows, user=user)

    async def get_tracks_by_album_artist_mbids(
        self,
        mbids: list[str],
        *,
        user: "UserRecord | None" = None,
        limit: int = 500,
    ) -> list[ViewTrack]:
        rows, _ = await self._store.list_target_tracks(
            limit=limit,
            offset=0,
            artist_ids=mbids,
            album_artist_only=True,
        )
        return await self.tracks_from_rows(rows, user=user)

    async def tracks_from_rows(
        self, rows: list[dict], *, user: "UserRecord | None" = None
    ) -> list[ViewTrack]:
        tracks = [self._track(row) for row in rows]
        await self._overlay_favorites(tracks, "track", user)
        await self._overlay_plays(tracks, "track", user)
        return tracks

    @staticmethod
    def _artist(row: dict) -> ViewArtist:
        return ViewArtist(
            artist_mbid=row["artist_mbid"],
            name=row["artist_name"],
            album_count=int(row["album_count"]),
            date_added=int(row["date_added"]) if row.get("date_added") else None,
            musicbrainz_artist_id=row.get("provider_artist_mbid"),
            provider_identity_projected=True,
        )

    @staticmethod
    def _album(row: dict) -> ViewAlbum:
        genres = [value for value in (row.get("genres") or "").split(",") if value]
        return ViewAlbum(
            rg_mbid=row["release_group_mbid"],
            title=row["album_title"],
            artist_name=row.get("album_artist_name"),
            artist_mbid=row.get("album_artist_mbid"),
            year=row.get("year"),
            genre=genres[0] if genres else None,
            track_count=int(row.get("track_count") or 0),
            total_duration_seconds=float(row.get("total_duration_seconds") or 0),
            cover_available=bool(row.get("cover_url")),
            date_added=int(row["last_imported_at"])
            if row.get("last_imported_at")
            else None,
            is_compilation=bool(row.get("is_compilation")),
            sort_name=row.get("album_sort_name"),
            original_release_date=row.get("original_release_date"),
            musicbrainz_release_group_id=row.get("provider_release_group_mbid"),
            musicbrainz_artist_id=row.get("provider_artist_mbid"),
            provider_identity_projected=True,
        )

    @classmethod
    def _album_from_tracks(cls, rows: list[dict]) -> ViewAlbum:
        first = rows[0]
        return ViewAlbum(
            rg_mbid=first["release_group_mbid"],
            title=first.get("canonical_album_title") or first.get("album_title") or "",
            artist_name=first.get("album_artist_name"),
            artist_mbid=first.get("album_artist_mbid"),
            year=first.get("year"),
            genre=_dominant_genre(rows),
            track_count=len(rows),
            total_duration_seconds=sum(
                float(row.get("duration_seconds") or 0) for row in rows
            ),
            cover_available=bool(first.get("cover_url")),
            date_added=int(max(float(row.get("imported_at") or 0) for row in rows)),
            is_compilation=bool(first.get("is_compilation")),
            sort_name=first.get("album_sort_name"),
            original_release_date=first.get("original_release_date"),
            disc_titles=list(
                dict.fromkeys(
                    (int(row.get("disc_number") or 1), row["disc_subtitle"])
                    for row in rows
                    if row.get("disc_subtitle")
                )
            ),
            musicbrainz_release_group_id=first.get("provider_release_group_mbid"),
            musicbrainz_artist_id=first.get("provider_album_artist_mbid"),
            provider_identity_projected=True,
        )

    @staticmethod
    def _track(row: dict) -> ViewTrack:
        return ViewTrack(
            file_id=row["id"],
            title=row.get("track_title") or "",
            album_title=row.get("canonical_album_title")
            or row.get("album_title")
            or "",
            rg_mbid=row.get("release_group_mbid"),
            artist_name=row.get("artist_name") or "",
            artist_mbid=row.get("artist_mbid"),
            album_artist_name=row.get("album_artist_name"),
            album_artist_mbid=row.get("album_artist_mbid"),
            track_number=int(row.get("track_number") or 0),
            disc_number=int(row.get("disc_number") or 1),
            year=row.get("year"),
            genre=row.get("genre"),
            duration_seconds=float(row.get("duration_seconds") or 0),
            file_format=(row.get("file_format") or "").lower(),
            bitrate=row.get("bit_rate"),
            sample_rate=row.get("sample_rate"),
            bit_depth=row.get("bit_depth"),
            channels=row.get("channels"),
            file_size_bytes=int(row.get("file_size_bytes") or 0),
            recording_mbid=row.get("recording_mbid"),
            file_path=row.get("file_path") or "",
            created_at=row.get("imported_at"),
            sort_name=row.get("track_sort_name"),
            artist_sort_name=row.get("artist_sort_name"),
            album_artist_sort_name=row.get("album_artist_sort_name"),
            album_sort_name=row.get("album_sort_name"),
            disc_subtitle=row.get("disc_subtitle"),
            original_release_date=row.get("original_release_date"),
            replaygain_track_gain=row.get("replaygain_track_gain"),
            replaygain_album_gain=row.get("replaygain_album_gain"),
            replaygain_track_peak=row.get("replaygain_track_peak"),
            replaygain_album_peak=row.get("replaygain_album_peak"),
            musicbrainz_recording_id=row.get("recording_mbid"),
            musicbrainz_release_group_id=row.get("provider_release_group_mbid"),
            musicbrainz_artist_id=row.get("provider_artist_mbid"),
            musicbrainz_album_artist_id=row.get("provider_album_artist_mbid"),
            provider_identity_projected=True,
        )

    @staticmethod
    def _item_id(item: ViewArtist | ViewAlbum | ViewTrack, kind: str) -> str:
        if kind == "artist":
            return item.artist_mbid  # type: ignore[union-attr]
        if kind == "album":
            return item.rg_mbid  # type: ignore[union-attr]
        return item.file_id  # type: ignore[union-attr]

    async def _overlay_favorites(
        self,
        items: list[ViewArtist] | list[ViewAlbum] | list[ViewTrack],
        kind: str,
        user: "UserRecord | None",
    ) -> None:
        if user is None or not items:
            return
        item_ids = [self._item_id(item, kind) for item in items]
        mapping = await self._favorites.map_for_items(user.id, kind, item_ids)
        for item in items:
            item.starred_at = mapping.get(self._item_id(item, kind))

    async def _overlay_plays(
        self,
        items: list[ViewArtist] | list[ViewAlbum] | list[ViewTrack],
        kind: str,
        user: "UserRecord | None",
    ) -> None:
        if self._history is None or user is None or not items:
            return
        item_ids = [self._item_id(item, kind) for item in items]
        stats = await self._history.compat_stats(
            user.id,
            recording_mbids=item_ids if kind == "track" else [],
            release_group_mbids=item_ids if kind == "album" else [],
            artist_names=item_ids if kind == "artist" else [],
        )
        for item in items:
            value = stats[kind].get(self._item_id(item, kind))
            if value is not None:
                item.play_count, item.played_at = value
