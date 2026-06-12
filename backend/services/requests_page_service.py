import logging
import math
import time as _time
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from api.v1.schemas.requests_page import (
    ActiveRequestItem,
    ActiveRequestsResponse,
    CancelRequestResponse,
    RequestHistoryItem,
    RequestHistoryResponse,
    RetryRequestResponse,
    StatusMessage,
)
from infrastructure.cover_urls import prefer_release_group_cover_url
from infrastructure.persistence.request_history import RequestHistoryRecord, RequestHistoryStore
from repositories.protocols import LidarrRepositoryProtocol
from services.request_utils import extract_cover_url, parse_eta, resolve_display_status

if TYPE_CHECKING:
    from infrastructure.queue.request_queue import RequestQueue

logger = logging.getLogger(__name__)

_CANCELLABLE_STATUSES = {"pending", "downloading"}
_RETRYABLE_STATUSES = {"failed", "cancelled", "incomplete"}
_CLEARABLE_STATUSES = {"imported", "incomplete", "failed", "cancelled"}

_QUEUE_CACHE_TTL = 10
_LIBRARY_MBIDS_CACHE_TTL = 30


class RequestsPageService:
    def __init__(
        self,
        lidarr_repo: LidarrRepositoryProtocol,
        request_history: RequestHistoryStore,
        library_mbids_fn: Callable[..., Coroutine[Any, Any, set[str]]],
        on_import_callback: Callable[[RequestHistoryRecord], Coroutine[Any, Any, None]] | None = None,
        request_queue: Optional["RequestQueue"] = None,
    ):
        self._lidarr_repo = lidarr_repo
        self._request_history = request_history
        self._library_mbids_fn = library_mbids_fn
        self._on_import_callback = on_import_callback
        self._request_queue = request_queue
        self._queue_cache: list[dict] | None = None
        self._queue_cache_time: float = 0
        self._library_mbids_cache: set[str] | None = None
        self._library_mbids_cache_time: float = 0

    async def get_active_requests(self, user_id: str | None = None) -> ActiveRequestsResponse:
        if user_id is not None:
            active_records = await self._request_history.async_get_active_requests_for_user(user_id)
        else:
            active_records = await self._request_history.async_get_active_requests()
        if not active_records:
            return ActiveRequestsResponse(items=[], count=0)

        queue_by_mbid = await self._load_queue_map(
            {r.musicbrainz_id for r in active_records}
        )
        library_mbids = await self._fetch_library_mbids()

        items: list[ActiveRequestItem] = []
        for record in active_records:
            # awaiting_approval records aren't in Lidarr, show them directly
            if record.status == "awaiting_approval":
                items.append(self._build_pending_item(record))
                continue

            queue_item = queue_by_mbid.get(record.musicbrainz_id)

            if queue_item:
                await self._sync_active_record(record, queue_item)
                items.append(self._build_active_item_from_queue(record, queue_item))
            else:
                completed = await self._check_if_completed(record, library_mbids)
                if completed:
                    continue
                items.append(self._build_pending_item(record))

        return ActiveRequestsResponse(items=items, count=len(items))

    async def get_request_history(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
        sort: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RequestHistoryResponse:
        if user_id is not None:
            records, total = await self._request_history.async_get_history_for_user(
                user_id=user_id, page=page, page_size=page_size, status_filter=status_filter, sort=sort
            )
        else:
            records, total = await self._request_history.async_get_history(
                page=page, page_size=page_size, status_filter=status_filter, sort=sort
            )

        library_mbids = await self._fetch_library_mbids()

        items = [
            RequestHistoryItem(
                musicbrainz_id=r.musicbrainz_id,
                artist_name=r.artist_name,
                album_title=r.album_title,
                artist_mbid=r.artist_mbid,
                year=r.year,
                cover_url=r.cover_url,
                requested_at=datetime.fromisoformat(r.requested_at),
                completed_at=(
                    datetime.fromisoformat(r.completed_at)
                    if r.completed_at
                    else None
                ),
                status=r.status,
                in_library=r.musicbrainz_id.lower() in library_mbids,
                user_id=r.user_id,
                requested_by_name=r.requested_by_name,
                reviewed_by_name=r.reviewed_by_name,
                reviewed_at=(
                    datetime.fromisoformat(r.reviewed_at)
                    if r.reviewed_at
                    else None
                ),
            )
            for r in records
        ]

        total_pages = max(1, math.ceil(total / page_size))

        return RequestHistoryResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def get_pending_approvals(self) -> ActiveRequestsResponse:
        records = await self._request_history.async_get_pending_approvals()
        items = [self._build_pending_item(r) for r in records]
        return ActiveRequestsResponse(items=items, count=len(items))

    async def get_pending_approval_count(self) -> int:
        return await self._request_history.async_get_pending_approval_count()

    async def approve_request(
        self, musicbrainz_id: str, reviewer_id: str, reviewer_name: str | None = None
    ) -> CancelRequestResponse:
        record = await self._request_history.async_get_record(musicbrainz_id)
        if not record:
            return CancelRequestResponse(success=False, message="Request not found")
        if record.status != "awaiting_approval":
            return CancelRequestResponse(
                success=False, message=f"Request is not awaiting approval (status: {record.status})"
            )
        await self._request_history.async_record_review(musicbrainz_id, "pending", reviewer_id, reviewer_name)
        if self._request_queue:
            try:
                await self._request_queue.enqueue(musicbrainz_id)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to enqueue approved request {musicbrainz_id}: {e}")
                await self._request_history.async_update_status(
                    musicbrainz_id, "failed",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                return CancelRequestResponse(
                    success=False, message=f"Approved but failed to queue: {record.album_title}"
                )
        return CancelRequestResponse(success=True, message=f"Approved: {record.album_title}")

    async def reject_request(
        self, musicbrainz_id: str, reviewer_id: str, reviewer_name: str | None = None
    ) -> CancelRequestResponse:
        record = await self._request_history.async_get_record(musicbrainz_id)
        if not record:
            return CancelRequestResponse(success=False, message="Request not found")
        if record.status != "awaiting_approval":
            return CancelRequestResponse(
                success=False, message=f"Request is not awaiting approval (status: {record.status})"
            )
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._request_history.async_record_review(
            musicbrainz_id, "rejected", reviewer_id, reviewer_name, completed_at=now_iso
        )
        return CancelRequestResponse(success=True, message=f"Rejected: {record.album_title}")

    async def cancel_request(
        self, musicbrainz_id: str, user_id: str | None = None
    ) -> CancelRequestResponse:
        record = await self._request_history.async_get_record(musicbrainz_id)
        if not record:
            return CancelRequestResponse(
                success=False, message="Request not found"
            )
        if user_id is not None and record.user_id != user_id:
            return CancelRequestResponse(success=False, message="Request not found")

        # awaiting_approval requests haven't reached Lidarr, cancel directly
        if record.status == "awaiting_approval":
            now_iso = datetime.now(timezone.utc).isoformat()
            await self._request_history.async_update_status(
                musicbrainz_id, "cancelled", completed_at=now_iso
            )
            return CancelRequestResponse(
                success=True,
                message=f"Cancelled request for {record.album_title}",
            )

        if record.status not in _CANCELLABLE_STATUSES:
            return CancelRequestResponse(
                success=False,
                message=f"Cannot cancel request with status '{record.status}'",
            )

        # Cancel from local queue first
        queue_cancelled = False
        if self._request_queue:
            queue_cancelled = await self._request_queue.cancel(musicbrainz_id)

        try:
            queue_items = await self._get_cached_queue()
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to fetch queue for cancel: %s", e)
            return CancelRequestResponse(
                success=False, message="Failed to reach Lidarr"
            )

        queue_id = None
        for item in queue_items:
            album_data = item.get("album", {})
            if album_data.get("foreignAlbumId", "").lower() == musicbrainz_id.lower():
                queue_id = item.get("id")
                break

        if queue_id:
            removed = await self._lidarr_repo.remove_queue_item(queue_id)
            if not removed:
                return CancelRequestResponse(
                    success=False, message="Couldn't remove the item from the download queue"
                )
            self._invalidate_queue_cache()
        elif not queue_cancelled:
            # Not in the local queue or Lidarr's download queue
            library_mbids = await self._fetch_library_mbids()
            if musicbrainz_id.lower() in library_mbids:
                return CancelRequestResponse(
                    success=False,
                    message="Album already imported, cannot cancel",
                )

        now_iso = datetime.now(timezone.utc).isoformat()
        await self._request_history.async_update_status(
            musicbrainz_id, "cancelled", completed_at=now_iso
        )

        return CancelRequestResponse(
            success=True,
            message=f"Cancelled download of {record.album_title}",
        )

    async def retry_request(
        self, musicbrainz_id: str, user_id: str | None = None
    ) -> RetryRequestResponse:
        record = await self._request_history.async_get_record(musicbrainz_id)
        if not record:
            return RetryRequestResponse(
                success=False, message="Request not found"
            )
        if user_id is not None and record.user_id != user_id:
            return RetryRequestResponse(success=False, message="Request not found")

        if record.status not in _RETRYABLE_STATUSES:
            return RetryRequestResponse(
                success=False,
                message=f"Cannot retry request with status '{record.status}'",
            )

        # If we have a Lidarr album ID, try a targeted search first
        if record.lidarr_album_id:
            result = await self._lidarr_repo.trigger_album_search(
                [record.lidarr_album_id]
            )
            if result:
                await self._request_history.async_update_status(musicbrainz_id, "pending")
                return RetryRequestResponse(
                    success=True,
                    message=f"Retrying search for {record.album_title}",
                )

        # Route through queue for dedup, per-artist locking, and history callbacks
        if self._request_queue:
            try:
                await self._request_history.async_update_status(musicbrainz_id, "pending")
                enqueued = await self._request_queue.enqueue(musicbrainz_id)
                if enqueued:
                    return RetryRequestResponse(
                        success=True,
                        message=f"Re-requested {record.album_title}",
                    )
                return RetryRequestResponse(
                    success=True,
                    message=f"Request already in queue for {record.album_title}",
                )
            except Exception as e:  # noqa: BLE001
                logger.error("Retry via queue failed for %s: %s", musicbrainz_id, e)
                return RetryRequestResponse(
                    success=False, message=f"Retry failed: {e}"
                )

        # Fallback: direct add_album (only if no queue available)
        try:
            add_result = await self._lidarr_repo.add_album(musicbrainz_id)
            payload = add_result.get("payload", {})
            if payload and isinstance(payload, dict):
                new_id = payload.get("id")
                if new_id:
                    await self._request_history.async_update_lidarr_album_id(
                        musicbrainz_id, new_id
                    )
            await self._request_history.async_update_status(musicbrainz_id, "pending")
            return RetryRequestResponse(
                success=True,
                message=f"Re-requested {record.album_title}",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Retry failed for %s: %s", musicbrainz_id, e)
            return RetryRequestResponse(
                success=False, message=f"Retry failed: {e}"
            )

    async def clear_history_item(self, musicbrainz_id: str, user_id: str | None = None) -> bool:
        record = await self._request_history.async_get_record(musicbrainz_id)
        if not record or record.status not in _CLEARABLE_STATUSES:
            return False
        if user_id is not None:
            if record.user_id != user_id:
                return False
            return await self._request_history.async_dismiss_record(user_id, musicbrainz_id)
        return await self._request_history.async_delete_record(musicbrainz_id)

    async def get_active_count(self, user_id: str | None = None) -> int:
        if user_id is not None:
            return await self._request_history.async_get_active_count_for_user(user_id)
        return await self._request_history.async_get_active_count()

    async def sync_request_statuses(self) -> None:
        active_records = await self._request_history.async_get_active_requests()
        if not active_records:
            return

        try:
            queue_items = await self._get_cached_queue()
        except Exception as e:  # noqa: BLE001
            logger.warning("Status sync failed - cannot reach Lidarr: %s", e)
            return

        queue_mbids: set[str] = set()
        for item in queue_items:
            album_data = item.get("album", {})
            mbid = album_data.get("foreignAlbumId")
            if mbid:
                queue_mbids.add(mbid.lower())

        library_mbids = await self._fetch_library_mbids()

        for record in active_records:
            if record.musicbrainz_id.lower() in queue_mbids:
                if record.status != "downloading":
                    await self._request_history.async_update_status(
                        record.musicbrainz_id, "downloading"
                    )
            else:
                await self._check_if_completed(record, library_mbids)


    async def _fetch_library_mbids(self) -> set[str]:
        now = _time.monotonic()
        if self._library_mbids_cache is not None and (now - self._library_mbids_cache_time) < _LIBRARY_MBIDS_CACHE_TTL:
            return self._library_mbids_cache
        try:
            result = await self._library_mbids_fn()
            self._library_mbids_cache = result
            self._library_mbids_cache_time = now
            return result
        except Exception:  # noqa: BLE001
            if self._library_mbids_cache is not None:
                return self._library_mbids_cache
            return set()

    async def _get_cached_queue(self) -> list[dict]:
        now = _time.monotonic()
        if self._queue_cache is not None and (now - self._queue_cache_time) < _QUEUE_CACHE_TTL:
            return self._queue_cache
        try:
            queue_items = await self._lidarr_repo.get_queue_details()
            self._queue_cache = queue_items
            self._queue_cache_time = now
            return queue_items
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to fetch Lidarr queue: %s", e)
            return self._queue_cache or []

    def _invalidate_queue_cache(self) -> None:
        self._queue_cache = None
        self._queue_cache_time = 0

    async def _load_queue_map(
        self, active_mbids: set[str]
    ) -> dict[str, dict]:
        queue_items = await self._get_cached_queue()

        normalized_active = {m.lower() for m in active_mbids}
        queue_by_mbid: dict[str, dict] = {}
        for item in queue_items:
            album_data = item.get("album", {})
            mbid = album_data.get("foreignAlbumId")
            if mbid and mbid.lower() in normalized_active:
                queue_by_mbid[mbid] = item
        return queue_by_mbid

    async def _sync_active_record(
        self,
        record: RequestHistoryRecord,
        queue_item: dict,
    ) -> None:
        if record.status != "downloading":
            await self._request_history.async_update_status(
                record.musicbrainz_id, "downloading"
            )

        if not record.cover_url:
            album_data = queue_item.get("album", {})
            cover_url = extract_cover_url(album_data)
            if cover_url:
                await self._request_history.async_update_cover_url(
                    record.musicbrainz_id, cover_url
                )
                record.cover_url = cover_url

    @staticmethod
    def _build_active_item_from_queue(
        record: RequestHistoryRecord,
        queue_item: dict,
    ) -> ActiveRequestItem:
        album_data = queue_item.get("album", {})
        artist_data = album_data.get("artist", {}) or queue_item.get("artist", {})

        cover_url = prefer_release_group_cover_url(
            record.musicbrainz_id,
            record.cover_url or extract_cover_url(album_data),
            size=500,
        )
        artist_mbid = record.artist_mbid or artist_data.get("foreignArtistId")

        size = queue_item.get("size")
        sizeleft = queue_item.get("sizeleft")
        progress = (
            round((size - (sizeleft or 0)) / size * 100, 1)
            if size and size > 0
            else None
        )

        eta = parse_eta(queue_item.get("estimatedCompletionTime"))

        status_messages = [
            StatusMessage(
                title=msg.get("title"),
                messages=msg.get("messages") or [],
            )
            for msg in (queue_item.get("statusMessages") or [])
        ] or None

        download_state = queue_item.get("trackedDownloadState")
        display_status = resolve_display_status(download_state)

        quality_data = queue_item.get("quality", {})
        quality_name = None
        if isinstance(quality_data, dict):
            quality_obj = quality_data.get("quality", {})
            if isinstance(quality_obj, dict):
                quality_name = quality_obj.get("name")

        return ActiveRequestItem(
            musicbrainz_id=record.musicbrainz_id,
            artist_name=record.artist_name,
            album_title=record.album_title,
            artist_mbid=artist_mbid,
            year=record.year,
            cover_url=cover_url,
            requested_at=datetime.fromisoformat(record.requested_at),
            status=display_status,
            progress=progress,
            eta=eta,
            size=size,
            size_remaining=sizeleft,
            download_status=queue_item.get("trackedDownloadStatus"),
            download_state=download_state,
            status_messages=status_messages,
            error_message=queue_item.get("errorMessage"),
            lidarr_queue_id=queue_item.get("id"),
            quality=quality_name,
            protocol=queue_item.get("protocol"),
            download_client=queue_item.get("downloadClient"),
            user_id=record.user_id,
            requested_by_name=record.requested_by_name,
        )

    @staticmethod
    def _build_pending_item(record: RequestHistoryRecord) -> ActiveRequestItem:
        return ActiveRequestItem(
            musicbrainz_id=record.musicbrainz_id,
            artist_name=record.artist_name,
            album_title=record.album_title,
            artist_mbid=record.artist_mbid,
            year=record.year,
            cover_url=prefer_release_group_cover_url(
                record.musicbrainz_id,
                record.cover_url,
                size=500,
            ),
            requested_at=datetime.fromisoformat(record.requested_at),
            status=record.status,
            progress=None,
            eta=None,
            size=None,
            size_remaining=None,
            download_status=None,
            download_state=None,
            status_messages=None,
            lidarr_queue_id=None,
            user_id=record.user_id,
            requested_by_name=record.requested_by_name,
        )

    async def _check_if_completed(
        self,
        record: RequestHistoryRecord,
        library_mbids: set[str],
    ) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()

        if record.musicbrainz_id.lower() in library_mbids:
            await self._request_history.async_update_status(
                record.musicbrainz_id, "imported", completed_at=now_iso
            )
            await self._notify_import(record)
            return True

        if record.lidarr_album_id:
            try:
                history = await self._lidarr_repo.get_history_for_album(
                    record.lidarr_album_id
                )
                for event in history:
                    event_type = event.get("eventType", "")
                    if event_type in (
                        "downloadImported",
                        "trackFileImported",
                    ):
                        await self._request_history.async_update_status(
                            record.musicbrainz_id,
                            "imported",
                            completed_at=now_iso,
                        )
                        await self._notify_import(record)
                        return True
                    if event_type == "albumImportIncomplete":
                        await self._request_history.async_update_status(
                            record.musicbrainz_id,
                            "incomplete",
                            completed_at=now_iso,
                        )
                        return True
                    if event_type == "downloadFailed":
                        await self._request_history.async_update_status(
                            record.musicbrainz_id,
                            "failed",
                            completed_at=now_iso,
                        )
                        return True
            except Exception as e:  # noqa: BLE001
                logger.debug("Lidarr history check failed for %s: %s", record.musicbrainz_id, e)

        return False

    async def _notify_import(self, record: RequestHistoryRecord) -> None:
        self._library_mbids_cache = None
        self._library_mbids_cache_time = 0
        if self._on_import_callback:
            try:
                await self._on_import_callback(record)
            except Exception as e:  # noqa: BLE001
                logger.warning("Import callback failed for %s: %s", record.musicbrainz_id, e)
