from infrastructure.msgspec_fastapi import AppStruct


class DiscoveryBatchItemIn(AppStruct):
    release_group_mbid: str
    artist_mbid: str = ""
    album_name: str = ""
    artist_name: str = ""


class DiscoveryBatchCreate(AppStruct):
    name: str
    source_section: str = ""
    items: list[DiscoveryBatchItemIn] = []


class DiscoveryBatchItemStatus(AppStruct):
    release_group_mbid: str
    artist_mbid: str = ""
    album_name: str = ""
    artist_name: str = ""
    # 'requested' | 'skipped_in_library' | 'skipped_duplicate'
    outcome: str = "requested"
    request_status: str | None = None
    in_library: bool = False


class DiscoveryBatchSummary(AppStruct):
    id: str
    name: str
    source_section: str = ""
    created_at: str = ""
    item_count: int = 0
    imported_count: int = 0
    pending_count: int = 0


class DiscoveryBatchDetail(DiscoveryBatchSummary):
    items: list[DiscoveryBatchItemStatus] = []


class DiscoveryBatchListResponse(AppStruct):
    batches: list[DiscoveryBatchSummary] = []


class DiscoveryBatchRemoveResult(AppStruct):
    removed_albums: int = 0
    cancelled_requests: int = 0
    kept: int = 0
