"""Plugin API routes (phase 01b).

Admin-only: list plugins, install one from GitHub, enable/disable, edit their
settings (mask-sentinel for secret fields), uninstall. There is deliberately no
route that makes a plugin acquire content (D22).
"""

import asyncio
import logging

from fastapi import APIRouter, Depends

from api.v1.schemas.plugins import (
    PLUGIN_SECRET_MASK,
    PluginInfo,
    PluginInstallRequest,
    PluginListResponse,
    PluginSettingFieldInfo,
    PluginUpdateRequest,
)
from api.v1.schemas.settings import PluginConfig
from core.dependencies import get_plugin_host, get_preferences_service
from api.v1.schemas.common import StatusMessageResponse
from core.exceptions import ResourceNotFoundError, ValidationError
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from middleware import CurrentAdminDep

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/plugins", tags=["plugins"])

# Route order: the literal path (/install) is declared before the /{plugin_name}
# handlers, so a future GET /{plugin_name} can never swallow it.


def _to_info(plugin, prefs) -> PluginInfo:  # noqa: ANN001 - LoadedPlugin / PreferencesService
    manifest = plugin.manifest
    config = prefs.get_plugin_config(manifest.name)
    values: dict[str, str] = {}
    for field in manifest.settings:
        stored = config.settings.get(field.key, "")
        values[field.key] = (PLUGIN_SECRET_MASK if stored else "") if field.secret else stored
    return PluginInfo(
        name=manifest.name,
        display_name=manifest.display_name,
        version=manifest.version,
        enabled=plugin.enabled,
        capabilities=manifest.capabilities,
        active_capabilities=plugin.active_capabilities,
        description=manifest.description,
        author=manifest.author,
        homepage=manifest.homepage,
        error=plugin.error,
        settings_fields=[
            PluginSettingFieldInfo(
                key=f.key, label=f.label, help=f.help, secret=f.secret
            )
            for f in manifest.settings
        ],
        settings_values=values,
    )


@router.get("", response_model=PluginListResponse)
async def list_plugins(
    _: CurrentAdminDep,
    host=Depends(get_plugin_host),
    prefs=Depends(get_preferences_service),
):
    return PluginListResponse(plugins=[_to_info(p, prefs) for p in host.list_plugins()])


@router.post("/install", response_model=PluginInfo, status_code=201)
async def install_plugin(
    _: CurrentAdminDep,
    body: PluginInstallRequest = MsgSpecBody(PluginInstallRequest),
    host=Depends(get_plugin_host),
    prefs=Depends(get_preferences_service),
):
    """Download a public GitHub repo into the plugins folder. The code is stored,
    never executed: the plugin arrives DISABLED and an admin must enable it,
    exactly like a hand-copied folder."""
    from infrastructure.http.client import HttpClientFactory
    from infrastructure.plugins.host import PluginInstallError

    http = HttpClientFactory.get_client(name="plugin-install", timeout=60.0)
    try:
        name = await host.install_from_github(body.repository_url, http)
    except PluginInstallError as exc:
        raise ValidationError(str(exc)) from exc
    plugin = host.get(name)
    if plugin is None:
        raise ValidationError("The plugin installed but could not be read back")
    return _to_info(plugin, prefs)


@router.put("/{plugin_name}", response_model=PluginInfo)
async def update_plugin(
    plugin_name: str,
    _: CurrentAdminDep,
    body: PluginUpdateRequest = MsgSpecBody(PluginUpdateRequest),
    host=Depends(get_plugin_host),
    prefs=Depends(get_preferences_service),
):
    plugin = host.get(plugin_name)
    if plugin is None:
        raise ResourceNotFoundError("Plugin not found")
    current = prefs.get_plugin_config(plugin_name)
    secret_keys = {f.key for f in plugin.manifest.settings if f.secret}
    merged: dict[str, str] = {}
    for key, value in body.settings.items():
        if key in secret_keys and value == PLUGIN_SECRET_MASK:
            merged[key] = current.settings.get(key, "")
        else:
            merged[key] = value
    prefs.save_plugin_config(plugin_name, PluginConfig(enabled=body.enabled, settings=merged))
    # reload so enable/disable and entrypoint changes apply immediately; module
    # import is blocking work, so keep it off the event loop
    await asyncio.to_thread(host.load_all)
    refreshed = host.get(plugin_name)
    if refreshed is None:
        raise ResourceNotFoundError("Plugin not found")
    return _to_info(refreshed, prefs)


@router.delete("/{plugin_name}", response_model=StatusMessageResponse)
async def uninstall_plugin(
    plugin_name: str,
    _: CurrentAdminDep,
    host=Depends(get_plugin_host),
):
    """Remove the plugin's folder. Its saved settings stay in config.json, so a
    reinstall picks them back up."""
    await asyncio.to_thread(host.uninstall, plugin_name)
    return StatusMessageResponse(status="ok", message=f"Removed {plugin_name}")
