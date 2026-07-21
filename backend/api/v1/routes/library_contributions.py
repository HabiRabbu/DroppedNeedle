from urllib.parse import quote

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from api.v1.schemas.library_contributions import (
    LibraryContributionDraftUpdateRequest,
    LibraryContributionResponse,
    LibraryContributionRevisionRequest,
    DiscogsReleaseSearchRequest,
    DiscogsReleaseSearchResponse,
    DiscogsSourceSelectRequest,
    ContributionAttachExistingRequest,
    ContributionDuplicateCheckRequest,
    ContributionMusicBrainzResultRequest,
    MusicBrainzSeedResponse,
)
from core.dependencies import LibraryContributionServiceDep
from core.exceptions import ConflictError, ResourceNotFoundError, ValidationError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentCuratorDep, CurrentUserDep

router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/library",
    tags=["library-contributions"],
)

_CALLBACK_ERROR_PATH = "/library?musicbrainz=callback-error"


def _callback_redirect(path: str) -> RedirectResponse:
    return RedirectResponse(
        path,
        status_code=303,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.get("/contributions/musicbrainz/callback", include_in_schema=False)
async def musicbrainz_contribution_callback(
    service: LibraryContributionServiceDep,
    token: str | None = None,
    release_mbid: str | None = None,
) -> RedirectResponse:
    try:
        contribution_id = await service.consume_musicbrainz_callback(
            token, release_mbid
        )
    except (ValidationError, ResourceNotFoundError, ConflictError):
        return _callback_redirect(_CALLBACK_ERROR_PATH)
    return _callback_redirect(
        f"/library/contributions/{quote(contribution_id, safe='')}?musicbrainz=returned"
    )


@router.post(
    "/albums/{album_id}/contributions",
    response_model=LibraryContributionResponse,
)
async def create_library_contribution(
    album_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
) -> LibraryContributionResponse:
    return LibraryContributionResponse(
        **dict(await service.create(album_id, current_user.id))
    )


@router.get(
    "/contributions/{contribution_id}",
    response_model=LibraryContributionResponse,
)
async def get_library_contribution(
    contribution_id: str,
    _current_user: CurrentUserDep,
    service: LibraryContributionServiceDep,
) -> LibraryContributionResponse:
    return LibraryContributionResponse(**dict(await service.get(contribution_id)))


@router.put(
    "/contributions/{contribution_id}/draft",
    response_model=LibraryContributionResponse,
)
async def update_library_contribution(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: LibraryContributionDraftUpdateRequest = MsgSpecBody(
        LibraryContributionDraftUpdateRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.update(
        contribution_id,
        expected_row_revision=body.expected_row_revision,
        draft=body.draft,
        actor_user_id=current_user.id,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/rebuild",
    response_model=LibraryContributionResponse,
)
async def rebuild_library_contribution(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: LibraryContributionRevisionRequest = MsgSpecBody(
        LibraryContributionRevisionRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.rebuild(
        contribution_id,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/cancel",
    response_model=LibraryContributionResponse,
)
async def cancel_library_contribution(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: LibraryContributionRevisionRequest = MsgSpecBody(
        LibraryContributionRevisionRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.cancel(
        contribution_id,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/discogs/search",
    response_model=DiscogsReleaseSearchResponse,
)
async def search_discogs_releases(
    contribution_id: str,
    _current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: DiscogsReleaseSearchRequest = MsgSpecBody(DiscogsReleaseSearchRequest),
) -> DiscogsReleaseSearchResponse:
    return DiscogsReleaseSearchResponse(
        results=await service.search_discogs(contribution_id, body.query)
    )


@router.post(
    "/contributions/{contribution_id}/discogs/select",
    response_model=LibraryContributionResponse,
)
async def select_discogs_release(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: DiscogsSourceSelectRequest = MsgSpecBody(DiscogsSourceSelectRequest),
) -> LibraryContributionResponse:
    contribution = await service.select_discogs(
        contribution_id,
        release_id_or_url=body.release_id_or_url,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/discogs/remove",
    response_model=LibraryContributionResponse,
)
async def remove_discogs_release(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: LibraryContributionRevisionRequest = MsgSpecBody(
        LibraryContributionRevisionRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.remove_discogs(
        contribution_id,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/musicbrainz/duplicates",
    response_model=LibraryContributionResponse,
)
async def check_musicbrainz_duplicates(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: ContributionDuplicateCheckRequest = MsgSpecBody(
        ContributionDuplicateCheckRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.check_duplicates(
        contribution_id,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
        different_edition_confirmed=body.different_edition_confirmed,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/musicbrainz/attach",
    response_model=LibraryContributionResponse,
)
async def attach_existing_musicbrainz_release(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: ContributionAttachExistingRequest = MsgSpecBody(
        ContributionAttachExistingRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.attach_existing(
        contribution_id,
        release_mbid=body.release_mbid,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/musicbrainz/seed",
    response_model=MusicBrainzSeedResponse,
)
async def create_musicbrainz_seed(
    contribution_id: str,
    request: Request,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: LibraryContributionRevisionRequest = MsgSpecBody(
        LibraryContributionRevisionRequest
    ),
) -> MusicBrainzSeedResponse:
    seed = await service.create_musicbrainz_seed(
        contribution_id,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
        public_base_url=str(request.base_url).rstrip("/"),
    )
    return MusicBrainzSeedResponse(**dict(seed))


@router.put(
    "/contributions/{contribution_id}/musicbrainz/result",
    response_model=LibraryContributionResponse,
)
async def record_musicbrainz_result(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: ContributionMusicBrainzResultRequest = MsgSpecBody(
        ContributionMusicBrainzResultRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.record_manual_result(
        contribution_id,
        release_id_or_url=body.release_id_or_url,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
        replace_existing_result=body.replace_existing_result,
    )
    return LibraryContributionResponse(**dict(contribution))


@router.post(
    "/contributions/{contribution_id}/musicbrainz/verify",
    response_model=LibraryContributionResponse,
)
async def retry_musicbrainz_verification(
    contribution_id: str,
    current_user: CurrentCuratorDep,
    service: LibraryContributionServiceDep,
    body: LibraryContributionRevisionRequest = MsgSpecBody(
        LibraryContributionRevisionRequest
    ),
) -> LibraryContributionResponse:
    contribution = await service.retry_verification(
        contribution_id,
        expected_row_revision=body.expected_row_revision,
        actor_user_id=current_user.id,
    )
    return LibraryContributionResponse(**dict(contribution))
