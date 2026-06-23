from datetime import datetime
from typing import Optional

from infrastructure.cover_urls import release_group_cover_url


_FAILED_STATES = {"downloadFailed", "downloadFailedPending", "importFailed"}
_IMPORT_BLOCKED_STATES = {"importBlocked", "importPending"}

_DOWNLOAD_STATE_MAP: dict[str, str] = {
    "downloading": "downloading",
    "importing": "importing",
    "imported": "imported",
    "paused": "paused",
    "downloadClientUnavailable": "downloadClientUnavailable",
    "queued": "queued",
}


def resolve_display_status(download_state: Optional[str]) -> str:
    if download_state in _FAILED_STATES:
        return "importFailed"
    if download_state in _IMPORT_BLOCKED_STATES:
        return "importBlocked"
    return _DOWNLOAD_STATE_MAP.get(download_state or "", "pending")


def parse_eta(eta_str: Optional[str]) -> Optional[datetime]:
    if not eta_str:
        return None
    try:
        return datetime.fromisoformat(eta_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def extract_cover_url(album_data: dict) -> Optional[str]:
    canonical_cover_url = release_group_cover_url(album_data.get("musicbrainz_id"), size=500)
    if canonical_cover_url:
        return canonical_cover_url

    images = album_data.get("images", [])
    for img in images:
        if img.get("coverType", "").lower() == "cover":
            return img.get("remoteUrl") or img.get("url")
    if images:
        return images[0].get("remoteUrl") or images[0].get("url")
    return None
