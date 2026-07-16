"""Target policy settings routes mounted only at the offline replacement boundary."""

from fastapi import APIRouter, Depends

from api.v1.schemas.library_policies import (
    LibraryPolicyApplyPreviewResponse,
    LibraryPolicyApplyRequest,
    LibraryPolicyImpactRequest,
    LibraryPolicyImpactResponse,
    LibraryPolicyTreeResponse,
    LibrarySettingsResponse,
    LibrarySettingsUpdateRequest,
)
from core.dependencies import TargetLibraryPolicyServiceDep
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentAdminDep


async def _admin_guard(_: CurrentAdminDep) -> None: ...


router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/settings/library",
    tags=["library-policies-target"],
    dependencies=[Depends(_admin_guard)],
)


@router.get("", response_model=LibrarySettingsResponse)
async def get_library_settings(
    service: TargetLibraryPolicyServiceDep,
) -> LibrarySettingsResponse:
    return await service.get_settings()


@router.put("", response_model=LibrarySettingsResponse)
async def update_library_settings(
    service: TargetLibraryPolicyServiceDep,
    request: LibrarySettingsUpdateRequest = MsgSpecBody(LibrarySettingsUpdateRequest),
) -> LibrarySettingsResponse:
    return await service.save_settings(
        request.settings,
        expected_policy_revision=request.expected_policy_revision,
    )


@router.get("/policy-tree", response_model=LibraryPolicyTreeResponse)
async def get_library_policy_tree(
    service: TargetLibraryPolicyServiceDep,
) -> LibraryPolicyTreeResponse:
    return await service.policy_tree()


@router.post("/policy-impact", response_model=LibraryPolicyImpactResponse)
async def preview_library_policy_impact(
    service: TargetLibraryPolicyServiceDep,
    request: LibraryPolicyImpactRequest = MsgSpecBody(LibraryPolicyImpactRequest),
) -> LibraryPolicyImpactResponse:
    return await service.preview_impact(request)


@router.post("/policy-apply-preview", response_model=LibraryPolicyApplyPreviewResponse)
async def preview_saved_policy_apply(
    service: TargetLibraryPolicyServiceDep,
    request: LibraryPolicyApplyRequest = MsgSpecBody(LibraryPolicyApplyRequest),
) -> LibraryPolicyApplyPreviewResponse:
    return await service.preview_apply(request)
