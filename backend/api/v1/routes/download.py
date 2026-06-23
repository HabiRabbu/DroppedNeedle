import logging

from fastapi import APIRouter, Depends, HTTPException
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from core.dependencies import get_local_files_service
from core.exceptions import ExternalServiceError, ResourceNotFoundError
from infrastructure.msgspec_fastapi import MsgSpecRoute
from services.local_files_service import LocalFilesService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/download", tags=["download"])


@router.get("/local/track/{track_id}")
async def download_track(
    track_id: str,
    local_service: LocalFilesService = Depends(get_local_files_service),
) -> FileResponse:
    try:
        file_path, filename, media_type = await local_service.get_download_track(track_id)
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=media_type,
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Track file not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Track file not found on disk")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied: path is outside the music directory")
    except ExternalServiceError as e:
        logger.error("Download error for track %s: %s", track_id, e)
        raise HTTPException(status_code=502, detail="Failed to retrieve track file")
    except OSError as e:
        logger.error("OS error downloading track %s: %s", track_id, e)
        raise HTTPException(status_code=500, detail="Failed to read track file")


@router.get("/local/album/{album_id}")
async def download_album(
    album_id: int,
    local_service: LocalFilesService = Depends(get_local_files_service),
) -> FileResponse:
    try:
        zip_path, zip_filename = await local_service.create_album_zip(album_id)
        return FileResponse(
            path=zip_path,
            filename=zip_filename,
            media_type="application/zip",
            headers={"Content-Encoding": "identity"},
            background=BackgroundTask(zip_path.unlink, missing_ok=True),
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Album or track files not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied: path is outside the music directory")
    except ExternalServiceError as e:
        logger.error("Download error for album %s: %s", album_id, e)
        raise HTTPException(status_code=502, detail="Failed to retrieve album data")
    except OSError as e:
        logger.error("OS error creating album ZIP %s: %s", album_id, e)
        raise HTTPException(status_code=500, detail="Failed to create album archive")


@router.get("/local/album/mbid/{mbid}")
async def download_album_by_mbid(
    mbid: str,
    local_service: LocalFilesService = Depends(get_local_files_service),
) -> FileResponse:
    try:
        zip_path, zip_filename = await local_service.create_album_zip_by_mbid(mbid)
        return FileResponse(
            path=zip_path,
            filename=zip_filename,
            media_type="application/zip",
            headers={"Content-Encoding": "identity"},
            background=BackgroundTask(zip_path.unlink, missing_ok=True),
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Album or track files not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied: path is outside the music directory")
    except ExternalServiceError as e:
        logger.error("Download error for album MBID %s: %s", mbid, e)
        raise HTTPException(status_code=502, detail="Failed to retrieve album data")
    except OSError as e:
        logger.error("OS error creating album ZIP for MBID %s: %s", mbid, e)
        raise HTTPException(status_code=500, detail="Failed to create album archive")
