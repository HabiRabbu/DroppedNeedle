"""Library scan control + progress routes.

``POST /scan/start`` launches the native ``LibraryScanner`` as a registered
background task (AUD-3); ``POST /scan/cancel`` signals it to stop. ``GET
/scan/status`` reads the persisted ``scan_state``; ``GET /scan/stream`` is the
SSE progress feed (singleton ``SSEPublisher``, mirroring
``api/v1/routes/cache_status.py``).
"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import msgspec

from api.v1.schemas.common import StatusMessageResponse
from api.v1.schemas.library import (
    LibraryScanStatusResponse,
    LibraryUnmatchedResponse,
    UnmatchedBatchFailure,
    UnmatchedBatchResolveRequest,
    UnmatchedBatchResolveResponse,
    UnmatchedResolveRequest,
)
from core.dependencies import (
    get_cache,
    get_library_manager,
    get_library_scanner,
    get_preferences_service,
    get_scan_state_store,
    get_sse_publisher,
)
from core.exceptions import ConfigurationError, ConflictError, ValidationError
from infrastructure.cache.cache_keys import musicbrainz_prefixes
from infrastructure.cache.memory_cache import CacheInterface
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from infrastructure.persistence.scan_state_store import ScanStateStore
from infrastructure.sse_publisher import SSEPublisher
from middleware import CurrentAdminDep, CurrentUserDep
from services.native.library_manager import LibraryManager
from services.native.library_scanner import LibraryScanner
from services.preferences_service import PreferencesService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/library", tags=["library-scan"])

_SCAN_CHANNEL = "library:scan"


def _log_scan_exception(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Library scan task failed: %s", task.exception())


@router.post("/scan/start", status_code=202, response_model=StatusMessageResponse)
async def start_scan(
    current_user: CurrentAdminDep,
    force: bool = Query(
        default=False,
        description="Force full re-scan: re-identify every file and clear the MB cache",
    ),
    scanner: LibraryScanner = Depends(get_library_scanner),
    scan_state: ScanStateStore = Depends(get_scan_state_store),
    preferences_service: PreferencesService = Depends(get_preferences_service),
    cache: CacheInterface = Depends(get_cache),
):
    state = await scan_state.get_state()
    if state["status"] == "scanning":
        raise ConflictError("A library scan is already running")
    library_paths = [
        Path(p) for p in preferences_service.get_library_settings_raw().library_paths
    ]
    if not library_paths:
        raise ConfigurationError(
            "No library paths are configured. Add a library path in Settings before scanning."
        )
    if force:
        # Wipe cached MB identifications so a forced re-scan re-fetches identities.
        for prefix in musicbrainz_prefixes():
            await cache.clear_prefix(prefix)
    from core.task_registry import TaskRegistry

    task = asyncio.create_task(scanner.scan(library_paths, force=force))
    try:
        # register raises RuntimeError if a same-named task is still running -
        # a genuine concurrent double-start. Surface it as 409, not 500.
        TaskRegistry.get_instance().register("library-scan", task)
    except RuntimeError as exc:
        task.cancel()
        raise ConflictError("A library scan is already running") from exc
    task.add_done_callback(_log_scan_exception)
    return StatusMessageResponse(status="started", message="Library scan started")


@router.post("/scan/cancel", response_model=StatusMessageResponse)
async def cancel_scan(
    current_user: CurrentAdminDep,
    scanner: LibraryScanner = Depends(get_library_scanner),
    scan_state: ScanStateStore = Depends(get_scan_state_store),
):
    state = await scan_state.get_state()
    if state["status"] != "scanning":
        raise ValidationError("No library scan is running")
    scanner.request_cancel()
    return StatusMessageResponse(status="cancelling", message="Cancelling library scan")


@router.get("/scan/status", response_model=LibraryScanStatusResponse)
async def scan_status(
    current_user: CurrentUserDep,
    scan_state: ScanStateStore = Depends(get_scan_state_store),
):
    state = await scan_state.get_state()
    return LibraryScanStatusResponse(**state)


@router.get("/scan/unmatched", response_model=LibraryUnmatchedResponse)
async def scan_unmatched(
    current_user: CurrentAdminDep,
    library_manager: LibraryManager = Depends(get_library_manager),
):
    # Admin-only: the unmatched list exposes on-disk file paths, and the
    # /library/unmatched page (and its resolve action) are admin-gated too.
    rows = await library_manager.get_unmatched()
    return LibraryUnmatchedResponse(items=rows, total=len(rows))


@router.post("/scan/unmatched/{review_id}/resolve", response_model=StatusMessageResponse)
async def resolve_unmatched(
    review_id: int,
    current_user: CurrentAdminDep,
    body: UnmatchedResolveRequest = MsgSpecBody(UnmatchedResolveRequest),
    scanner: LibraryScanner = Depends(get_library_scanner),
):
    """Resolve a manual-review entry (accept / reject / manual_id). 404 if the
    entry is unknown or already resolved; 400 on a bad resolution / missing MBID."""
    await scanner.resolve_unmatched(review_id, body.resolution, body.mbid)
    return StatusMessageResponse(status="resolved", message="Unmatched file resolved")


@router.post(
    "/scan/unmatched/resolve-batch", response_model=UnmatchedBatchResolveResponse
)
async def resolve_unmatched_batch(
    current_user: CurrentAdminDep,
    body: UnmatchedBatchResolveRequest = MsgSpecBody(UnmatchedBatchResolveRequest),
    scanner: LibraryScanner = Depends(get_library_scanner),
):
    """Attribute several unmatched files to one album at once."""
    result = await scanner.resolve_unmatched_batch(
        body.release_group_mbid,
        [(item.review_id, item.recording_mbid) for item in body.items],
    )
    return UnmatchedBatchResolveResponse(
        resolved=result["resolved"],
        failed=[
            UnmatchedBatchFailure(review_id=f["review_id"], error=f["error"])
            for f in result["failed"]
        ],
    )


@router.get("/scan/stream")
async def scan_stream(
    current_user: CurrentUserDep,
    publisher: SSEPublisher = Depends(get_sse_publisher),
):
    async def event_generator():
        try:
            async for message in publisher.subscribe(_SCAN_CHANNEL):
                if not message["event"]:  # keepalive heartbeat (AUD-4)
                    yield ": keepalive\n\n"
                    continue
                payload = msgspec.json.encode(message["data"]).decode("utf-8")
                yield f"event: {message['event']}\ndata: {payload}\n\n"
        except asyncio.CancelledError:  # pragma: no cover - client disconnect
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
