from datetime import datetime
from infrastructure.msgspec_fastapi import AppStruct


class StatusMessage(AppStruct):
    title: str | None = None
    messages: list[str] = []


class ActiveRequestItem(AppStruct):
    musicbrainz_id: str
    artist_name: str
    album_title: str
    requested_at: datetime
    status: str
    artist_mbid: str | None = None
    year: int | None = None
    cover_url: str | None = None
    progress: float | None = None
    eta: datetime | None = None
    size: float | None = None
    size_remaining: float | None = None
    download_status: str | None = None
    download_state: str | None = None
    status_messages: list[StatusMessage] | None = None
    error_message: str | None = None
    lidarr_queue_id: int | None = None
    quality: str | None = None
    protocol: str | None = None
    download_client: str | None = None
    user_id: str | None = None


class RequestHistoryItem(AppStruct):
    musicbrainz_id: str
    artist_name: str
    album_title: str
    requested_at: datetime
    status: str
    artist_mbid: str | None = None
    year: int | None = None
    cover_url: str | None = None
    completed_at: datetime | None = None
    in_library: bool = False
    user_id: str | None = None


class ActiveRequestsResponse(AppStruct):
    items: list[ActiveRequestItem]
    count: int


class RequestHistoryResponse(AppStruct):
    items: list[RequestHistoryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class CancelRequestResponse(AppStruct):
    success: bool
    message: str


class RetryRequestResponse(AppStruct):
    success: bool
    message: str


class ClearHistoryResponse(AppStruct):
    success: bool


class ActiveCountResponse(AppStruct):
    count: int


class ApprovalActionResponse(AppStruct):
    success: bool
    message: str
