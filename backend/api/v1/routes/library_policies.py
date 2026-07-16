"""Administrator routes for typed library roots and policy previews."""

from fastapi import APIRouter, Depends

from api.v1.schemas.library_policies import (
    LibraryPathMappingReport,
    LibraryPolicyImpactRequest,
    LibraryPolicyImpactResponse,
    LibraryPolicyTreeResponse,
    LibrarySettingsResponse,
    LibrarySettingsUpdateRequest,
)
from core.dependencies import LibraryPolicyServiceDep
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentAdminDep


async def _admin_guard(_: CurrentAdminDep) -> None: ...


router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/settings/library",
    tags=["library-policies"],
    dependencies=[Depends(_admin_guard)],
)


@router.get("/roots", response_model=LibrarySettingsResponse)
async def get_typed_library_settings(
    service: LibraryPolicyServiceDep,
) -> LibrarySettingsResponse:
    return service.get_settings()


@router.put("/roots", response_model=LibrarySettingsResponse)
async def update_typed_library_settings(
    service: LibraryPolicyServiceDep,
    request: LibrarySettingsUpdateRequest = MsgSpecBody(LibrarySettingsUpdateRequest),
) -> LibrarySettingsResponse:
    return service.save_settings(
        request.settings,
        expected_policy_revision=request.expected_policy_revision,
    )


@router.get("/policy-tree", response_model=LibraryPolicyTreeResponse)
async def get_library_policy_tree(
    service: LibraryPolicyServiceDep,
) -> LibraryPolicyTreeResponse:
    return service.policy_tree()


@router.post("/policy-impact", response_model=LibraryPolicyImpactResponse)
async def preview_library_policy_impact(
    service: LibraryPolicyServiceDep,
    request: LibraryPolicyImpactRequest = MsgSpecBody(LibraryPolicyImpactRequest),
) -> LibraryPolicyImpactResponse:
    return service.preview_impact(request)


@router.get("/path-mapping", response_model=LibraryPathMappingReport)
async def get_library_path_mapping(
    service: LibraryPolicyServiceDep,
) -> LibraryPathMappingReport:
    return await service.dry_run_path_mapping()
