"""Discovery batches: explicit "download this whole section" with reversible removal.

Nothing is ever automatic - a batch exists only because the user pressed
"Download all" and confirmed. Role/quota rules are exactly the normal request
rules (RequestService.request_batch); removal only ever touches albums THIS
batch requested (pre-existing library albums and duplicates are never removed),
and imported files go to the recycle bin, not the shredder.
"""

import logging
from typing import Any

from api.v1.schemas.discovery_batches import (
    DiscoveryBatchCreate,
    DiscoveryBatchDetail,
    DiscoveryBatchItemStatus,
    DiscoveryBatchRemoveResult,
    DiscoveryBatchSummary,
)
from core.exceptions import ResourceNotFoundError, ValidationError
from infrastructure.persistence.discovery_batch_store import DiscoveryBatchStore
from infrastructure.persistence.request_history import RequestHistoryStore

logger = logging.getLogger(__name__)

MAX_BATCH_ITEMS = 30

# request-history statuses that mean "still cancellable, nothing on disk yet"
_PENDING_STATUSES = {"awaiting_approval", "pending", "searching", "downloading", "processing"}
_IMPORTED_STATUSES = {"completed", "imported"}


class DiscoveryBatchService:
    def __init__(
        self,
        batch_store: DiscoveryBatchStore,
        request_service: Any,
        request_history: RequestHistoryStore,
        library_service: Any,
        library_db: Any,
        get_download_service: Any = None,
    ) -> None:
        self._batches = batch_store
        self._requests = request_service
        self._history = request_history
        self._library_service = library_service
        self._library_db = library_db
        # Purge-only, policy-independent; kept as a getter for consistency with the
        # other download-service holders (a settings save rebuilds the singleton).
        self._get_download_service = get_download_service

    async def create(
        self, user_id: str, user_role: str, requested_by_name: str, body: DiscoveryBatchCreate
    ) -> DiscoveryBatchDetail:
        if not body.items:
            raise ValidationError("A discovery batch needs at least one album")
        if len(body.items) > MAX_BATCH_ITEMS:
            raise ValidationError(f"A discovery batch is capped at {MAX_BATCH_ITEMS} albums")
        name = body.name.strip() or "Discovery batch"

        library_mbids: set[str] = set()
        try:
            library_mbids = {m.lower() for m in await self._library_db.get_all_album_mbids()}
        except Exception:  # noqa: BLE001
            logger.warning("Discovery batch: library membership check failed; treating all as new")
        active = await self._history.async_get_active_mbids()

        rows: list[dict[str, Any]] = []
        to_request: list[dict[str, Any]] = []
        seen_item_mbids: set[str] = set()
        for item in body.items:
            mbid_lower = item.release_group_mbid.lower()
            if mbid_lower in seen_item_mbids:
                continue
            seen_item_mbids.add(mbid_lower)
            if mbid_lower in library_mbids:
                outcome = "skipped_in_library"
            elif mbid_lower in active:
                outcome = "skipped_duplicate"
            else:
                outcome = "requested"
                to_request.append({
                    "musicbrainz_id": item.release_group_mbid,
                    "artist_name": item.artist_name or "Unknown",
                    "album_title": item.album_name or "Unknown",
                    "artist_mbid": item.artist_mbid or None,
                })
            rows.append({
                "release_group_mbid": item.release_group_mbid,
                "artist_mbid": item.artist_mbid,
                "album_name": item.album_name,
                "artist_name": item.artist_name,
                "outcome": outcome,
            })

        if not to_request:
            raise ValidationError(
                "Every album in this batch is already in your library or already requested"
            )

        # quota/role rules live in request_batch; over-quota rejects the whole batch
        # (domain exception propagates - no batch row is created)
        await self._requests.request_batch(
            items=to_request,
            user_id=user_id,
            user_role=user_role,
            requested_by_name=requested_by_name,
        )

        batch_id = await self._batches.create_batch(user_id, name, body.source_section, rows)
        return await self.get_detail(user_id, user_role, batch_id)

    async def _summarise(self, batch: dict[str, Any], items: list[dict[str, Any]]) -> DiscoveryBatchSummary:
        statuses = await self._item_statuses(items)
        imported = sum(1 for s in statuses if s.in_library)
        pending = sum(
            1 for s in statuses
            if s.outcome == "requested" and not s.in_library
            and (s.request_status or "") in _PENDING_STATUSES
        )
        return DiscoveryBatchSummary(
            id=batch["id"],
            name=batch["name"],
            source_section=batch.get("source_section", ""),
            created_at=batch["created_at"],
            item_count=len(items),
            imported_count=imported,
            pending_count=pending,
        )

    async def _item_statuses(self, items: list[dict[str, Any]]) -> list[DiscoveryBatchItemStatus]:
        library_mbids: set[str] = set()
        try:
            library_mbids = {m.lower() for m in await self._library_db.get_all_album_mbids()}
        except Exception:  # noqa: BLE001
            pass
        out: list[DiscoveryBatchItemStatus] = []
        for item in items:
            record = await self._history.async_get_record(item["release_group_mbid"])
            out.append(DiscoveryBatchItemStatus(
                release_group_mbid=item["release_group_mbid"],
                artist_mbid=item.get("artist_mbid", ""),
                album_name=item.get("album_name", ""),
                artist_name=item.get("artist_name", ""),
                outcome=item.get("outcome", "requested"),
                request_status=record.status if record else None,
                in_library=item["release_group_mbid"].lower() in library_mbids,
            ))
        return out

    async def list_for_user(self, user_id: str) -> list[DiscoveryBatchSummary]:
        batches = await self._batches.list_batches(user_id)
        items_by_batch = await self._batches.get_items_for_batches([b["id"] for b in batches])
        return [
            await self._summarise(batch, items_by_batch.get(batch["id"], []))
            for batch in batches
        ]

    async def _authorised_batch(self, user_id: str, user_role: str, batch_id: str) -> dict[str, Any]:
        batch = await self._batches.get_batch(batch_id)
        # non-owners get a 404, not a 403: don't reveal the batch exists
        if batch is None or (batch["user_id"] != user_id and user_role != "admin"):
            raise ResourceNotFoundError("Batch not found")
        return batch

    async def get_detail(self, user_id: str, user_role: str, batch_id: str) -> DiscoveryBatchDetail:
        batch = await self._authorised_batch(user_id, user_role, batch_id)
        items = await self._batches.get_items(batch_id)
        summary = await self._summarise(batch, items)
        return DiscoveryBatchDetail(
            id=summary.id,
            name=summary.name,
            source_section=summary.source_section,
            created_at=summary.created_at,
            item_count=summary.item_count,
            imported_count=summary.imported_count,
            pending_count=summary.pending_count,
            items=await self._item_statuses(items),
        )

    async def remove(
        self, user_id: str, user_role: str, batch_id: str, remove_albums: bool
    ) -> DiscoveryBatchRemoveResult:
        batch = await self._authorised_batch(user_id, user_role, batch_id)
        items = await self._batches.get_items(batch_id)

        removed_albums = 0
        cancelled = 0
        kept = 0

        if remove_albums:
            statuses = await self._item_statuses(items)
            for status in statuses:
                # ONLY albums this batch caused: skipped items are never touched
                if status.outcome != "requested":
                    kept += 1
                    continue
                mbid = status.release_group_mbid
                if status.in_library:
                    try:
                        await self._library_service.remove_album(mbid, to_recycle=True)
                        removed_albums += 1
                    except Exception as e:  # noqa: BLE001 - keep going; report what worked
                        logger.warning("Batch removal: album %s failed: %s", mbid[:8], e)
                        kept += 1
                        continue
                    download_service = (
                        self._get_download_service() if self._get_download_service is not None else None
                    )
                    if download_service is not None:
                        try:
                            await download_service.purge_album_downloads(mbid)
                        except Exception as e:  # noqa: BLE001 - cleanup must not fail removal
                            logger.warning("Batch removal: purge failed for %s: %s", mbid[:8], e)
                elif (status.request_status or "") in _PENDING_STATUSES:
                    result = await self._requests.cancel_batch(
                        [mbid],
                        user_id=None if user_role == "admin" else batch["user_id"],
                        user_role=user_role,
                    )
                    if result.cancelled:
                        cancelled += 1
                    else:
                        kept += 1
                else:
                    kept += 1
        else:
            kept = len(items)

        await self._batches.delete_batch(batch_id)
        return DiscoveryBatchRemoveResult(
            removed_albums=removed_albums,
            cancelled_requests=cancelled,
            kept=kept,
        )
