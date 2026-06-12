import asyncio
import httpx
import msgspec
import time
from typing import Any, Optional
from core.config import Settings
from core.exceptions import ExternalServiceError
from infrastructure.cache.cache_keys import lidarr_raw_albums_key, lidarr_requested_mbids_key, lidarr_monitored_mbids_key, LIDARR_PREFIX
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.http.deduplication import get_deduplicator
from infrastructure.resilience.retry import with_retry, CircuitBreaker

_lidarr_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0,
    name="lidarr"
)

LidarrJsonObject = dict[str, Any]
LidarrJsonArray = list[LidarrJsonObject]
LidarrJson = LidarrJsonObject | LidarrJsonArray

# Large Lidarr libraries make /api/v1/album an expensive page-path dependency.
LIDARR_LIBRARY_SCAN_TTL_SECONDS = 3600


def reset_lidarr_circuit_breaker():
    _lidarr_circuit_breaker.reset()


def _decode_json_response(response: httpx.Response) -> LidarrJson:
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray, memoryview)):
        return msgspec.json.decode(content, type=LidarrJson)
    return response.json()


class LidarrBase:
    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
        cache: CacheInterface
    ):
        self._settings = settings
        self._client = http_client
        self._cache = cache

    @property
    def _base_url(self) -> str:
        return self._settings.lidarr_url.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self._settings.lidarr_api_key)

    def _get_headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self._settings.lidarr_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @with_retry(
        max_attempts=3,
        base_delay=1.0,
        max_delay=5.0,
        circuit_breaker=_lidarr_circuit_breaker,
        retriable_exceptions=(httpx.HTTPError, ExternalServiceError)
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
    ) -> Any:
        if not self.is_configured():
            raise ExternalServiceError("Lidarr is not configured (no API key)")

        path = endpoint.lstrip("/")
        url = f"{self._base_url}/{path}" if path else self._base_url

        timeout = httpx.Timeout(
            self._settings.lidarr_timeout,
            connect=self._settings.http_connect_timeout,
        )

        try:
            response = await self._client.request(
                method,
                url,
                headers=self._get_headers(),
                params=params,
                json=json_data,
                timeout=timeout,
            )

            if method == "DELETE" and response.status_code in (200, 202, 204):
                if response.status_code == 204 or not response.content:
                    return None
            elif method == "DELETE":
                raise ExternalServiceError(
                    f"Lidarr {method} failed ({response.status_code})",
                    response.text
                )
            elif method == "GET" and response.status_code != 200:
                raise ExternalServiceError(
                    f"Lidarr {method} failed ({response.status_code})",
                    response.text
                )
            elif method in ("POST", "PUT") and response.status_code not in (200, 201, 202):
                raise ExternalServiceError(
                    f"Lidarr {method} failed ({response.status_code})",
                    response.text
                )

            try:
                return _decode_json_response(response)
            except (msgspec.DecodeError, ValueError, TypeError):
                return None

        except httpx.HTTPError as e:
            raise ExternalServiceError(f"Lidarr request failed: {str(e)}")

    async def _get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> Any:
        return await self._request("GET", endpoint, params=params)

    async def _get_all_albums_raw(self) -> list[dict[str, Any]]:
        cache_key = lidarr_raw_albums_key()
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached if isinstance(cached, list) else []

        deduplicator = get_deduplicator()
        data = await deduplicator.dedupe(cache_key, lambda: self._get("/api/v1/album"))
        if not isinstance(data, list):
            return []

        await self._cache.set(cache_key, data, ttl_seconds=LIDARR_LIBRARY_SCAN_TTL_SECONDS)
        return data

    async def _invalidate_album_list_caches(self) -> None:
        await self._cache.delete(lidarr_raw_albums_key())
        await self._cache.clear_prefix(f"{LIDARR_PREFIX}library:")
        await self._cache.delete(lidarr_requested_mbids_key())
        await self._cache.delete(lidarr_monitored_mbids_key())

    async def _post(self, endpoint: str, data: dict[str, Any]) -> Any:
        return await self._request("POST", endpoint, json_data=data)

    async def _put(self, endpoint: str, data: dict[str, Any]) -> Any:
        return await self._request("PUT", endpoint, json_data=data)

    async def _delete(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> Any:
        return await self._request("DELETE", endpoint, params=params)

    async def _post_command(self, body: dict[str, Any]) -> Any:
        try:
            return await self._post("/api/v1/command", body)
        except ExternalServiceError:
            return None

    async def _get_command(self, cmd_id: int) -> Any:
        return await self._get(f"/api/v1/command/{cmd_id}")

    async def _await_command(self, body: dict[str, Any], timeout: float = 60.0, poll: float = 0.5) -> dict[str, Any] | None:
        try:
            cmd = await self._post_command(body)
            if not cmd or "id" not in cmd:
                await asyncio.sleep(min(timeout, 5.0))
                return None

            cmd_id = cmd["id"]
            deadline = time.monotonic() + timeout
            last_status = None

            while time.monotonic() < deadline:
                await asyncio.sleep(poll)
                try:
                    status = await self._get_command(cmd_id)
                    last_status = status
                except ExternalServiceError:
                    continue

                state = (status or {}).get("status") or (status or {}).get("state")
                if str(state).lower() in {"completed", "failed", "aborted", "cancelled"}:
                    return status

            return last_status
        except ExternalServiceError:
            return None

    async def _wait_for(
        self,
        fetch_coro_factory,
        stop=lambda v: bool(v),
        timeout: float = 30.0,
        poll: float = 0.5
    ):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = await fetch_coro_factory()
                if stop(last):
                    return last
            except ExternalServiceError:
                pass
            await asyncio.sleep(poll)
        return last

    def _build_api_media_cover_url(self, artist_id: int, url_path: str, size: Optional[int]) -> str:
        path_part = url_path.split("?")[0]
        filename = path_part.rsplit("/", 1)[-1] if "/" in path_part else path_part

        if size and "." in filename:
            base, ext = filename.rsplit(".", 1)
            if not base.endswith(f"-{size}"):
                filename = f"{base}-{size}.{ext}"

        return f"{self._base_url}/api/v1/MediaCover/artist/{artist_id}/{filename}?apikey={self._settings.lidarr_api_key}"

    def _build_api_media_cover_url_album(self, album_id: int, url_path: str, size: Optional[int]) -> str:
        path_part = url_path.split("?")[0]
        filename = path_part.rsplit("/", 1)[-1] if "/" in path_part else path_part

        if size and "." in filename:
            base, ext = filename.rsplit(".", 1)
            if not base.endswith(f"-{size}"):
                filename = f"{base}-{size}.{ext}"

        return f"{self._base_url}/api/v1/MediaCover/album/{album_id}/{filename}?apikey={self._settings.lidarr_api_key}"

    def _get_album_cover_url(self, images: list[dict], album_id: Optional[int], size: int = 500) -> Optional[str]:
        if not images:
            return None

        cover_url = None
        for img in images:
            cover_type = img.get("coverType", "").lower()
            remote_url = img.get("remoteUrl")
            local_url = img.get("url", "")

            if remote_url:
                constructed_url = remote_url
            elif local_url and local_url.startswith("http"):
                constructed_url = local_url
            elif local_url and album_id:
                constructed_url = self._build_api_media_cover_url_album(album_id, local_url, size)
            else:
                continue

            if cover_type == "cover":
                return constructed_url
            elif not cover_url:
                cover_url = constructed_url

        return cover_url

    def _get_artist_image_urls(self, images: list[dict], artist_id: Optional[int], size: int = 500) -> dict[str, Optional[str]]:
        result: dict[str, Optional[str]] = {"poster": None, "fanart": None, "banner": None}

        if not images:
            return result

        for img in images:
            cover_type = img.get("coverType", "").lower()
            if cover_type not in result:
                continue

            remote_url = img.get("remoteUrl")
            local_url = img.get("url", "")

            if remote_url:
                constructed_url = remote_url
            elif local_url and local_url.startswith("http"):
                constructed_url = local_url
            elif local_url and artist_id:
                constructed_url = self._build_api_media_cover_url(artist_id, local_url, size)
            else:
                continue

            if not result[cover_type]:
                result[cover_type] = constructed_url

        return result
