"""Navidrome 0.62.0 ASGI mock based on the sanitized 2026-07-13 live probe.

The probed server exposed one folder. It accepted the same ``musicFolderId``
twice and ignored an unknown folder for catalog endpoints. Two-folder behavior
was not observable and is deliberately not modeled here.
"""

from fastapi import FastAPI, Request


class Navidrome062Mock:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.music_folder_requests: dict[str, list[list[str]]] = {}
        self.app.add_api_route(
            "/rest/{endpoint}", self.handle, methods=["GET"]
        )

    async def handle(self, endpoint: str, request: Request) -> dict:
        folder_ids = [
            value
            for key, value in request.query_params.multi_items()
            if key == "musicFolderId"
        ]
        self.music_folder_requests.setdefault(endpoint, []).append(folder_ids)

        payload = self._payload(endpoint)
        return {
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "serverVersion": "0.62.0 (sanitized)",
                **payload,
            }
        }

    @staticmethod
    def _payload(endpoint: str) -> dict:
        artist = {"id": "artist-1", "name": "Artist", "albumCount": 1}
        album = {
            "id": "album-1",
            "name": "Album",
            "artist": "Artist",
            "artistId": "artist-1",
            "songCount": 1,
            "duration": 180,
        }
        song = {
            "id": "song-1",
            "title": "Song",
            "album": "Album",
            "albumId": "album-1",
            "artist": "Artist",
            "artistId": "artist-1",
            "duration": 180,
            "suffix": "flac",
        }
        if endpoint == "ping":
            return {}
        if endpoint == "getMusicFolders":
            return {
                "musicFolders": {
                    "musicFolder": [{"id": "folder-1", "name": "Library"}]
                }
            }
        if endpoint == "getArtists":
            return {"artists": {"index": [{"name": "A", "artist": [artist]}]}}
        if endpoint == "getAlbumList2":
            return {"albumList2": {"album": [album]}}
        if endpoint == "search3":
            return {"searchResult3": {"artist": [artist], "album": [album], "song": [song]}}
        if endpoint == "getGenres":
            return {"genres": {"genre": [{"value": "Genre", "songCount": 1, "albumCount": 1}]}}
        if endpoint == "getSongsByGenre":
            return {"songsByGenre": {"song": [song]}}
        if endpoint == "getStarred2":
            return {"starred2": {}}
        if endpoint == "getRandomSongs":
            return {"randomSongs": {"song": [song]}}
        return {}

