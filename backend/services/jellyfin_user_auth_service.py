"""Jellyfin user authentication service"""

from __future__ import annotations

import json, logging, sqlite3, uuid

import httpx

from core.exceptions import AuthenticationError, ExternalServiceError
from infrastructure.crypto import encrypt
from infrastructure.persistence.auth_store import AuthStore, UserRecord, _derive_username

logger = logging.getLogger(__name__)

# Sent as `Authorization`, not the legacy `X-Emby-Authorization` header Jellyfin
# 10.11 removed alongside X-Emby-Token (issue #151); both spellings of the value
# are accepted by older servers.
_EMBY_AUTH_HEADER = (
    'MediaBrowser Client="DroppedNeedle", Device="DroppedNeedle", DeviceId="{client_id}", Version="1.4.0"'
)


class JellyfinUserAuthService:
    def __init__(
        self,
        auth_store: AuthStore,
        jellyfin_repository,
        preferences_service,
        connections_store=None,
        cache=None,
    ) -> None:
        self._store = auth_store
        self._jellyfin_repo = jellyfin_repository
        self._prefs = preferences_service
        self._connections_store = connections_store
        self._cache = cache

    async def login(
        self,
        *,
        username: str,
        password: str,
        user_agent: str | None = None,
    ) -> tuple[UserRecord, str]:
        if not self._jellyfin_repo.is_configured():
            raise AuthenticationError("Jellyfin is not configured on this server")

        profile = await self._authenticate_with_jellyfin(username, password)

        user = await self._find_or_create_user(profile)

        # auto-link the per-user media connection (D4): the login just handed us a
        # fresh user-scoped token, so playback attribution works with zero setup
        await self._auto_link_connection(user.id, profile)

        raw_token, token_hash = self._store.issue_token()
        await self._store.store_token(
            id = str(uuid.uuid4()),
            user_id = user.id,
            token_hash = token_hash,
            user_agent = user_agent,
        )
        await self._store.update_last_login(user.id)

        logger.info(f"Jellyfin login: {user.display_name} ({user.id[:8]}')")
        return user, raw_token

    async def authenticate_credentials(self, username: str, password: str) -> dict:
        """Validate a Jellyfin username/password and return the auth profile
        (jellyfin_user_id / username / access_token) without any DroppedNeedle
        login side effects. Used by the per-user connection link flow."""
        if not self._jellyfin_repo.is_configured():
            raise AuthenticationError("Jellyfin is not configured on this server")
        return await self._authenticate_with_jellyfin(username, password)

    async def _auto_link_connection(self, user_id: str, profile: dict) -> None:
        if self._connections_store is None:
            return
        try:
            await self._connections_store.upsert(
                user_id,
                "jellyfin",
                {
                    "access_token": profile["access_token"],
                    "jellyfin_user_id": profile["jellyfin_user_id"],
                    "username": profile["username"],
                },
            )
            if self._cache is not None:
                from services.media_playlist_cache import invalidate_media_playlist_cache

                await invalidate_media_playlist_cache(
                    self._cache, user_id, "jellyfin"
                )
        except Exception:  # noqa: BLE001 - a failed auto-link must never fail the login
            logger.warning(
                "Failed to auto-link Jellyfin connection for user %s", user_id[:8], exc_info=True
            )

    async def _authenticate_with_jellyfin(self, username: str, password: str) -> dict:
        client_id = self._prefs.get_or_create_setting(
            "droppedneedle_device_id", lambda: str(uuid.uuid4())
        )

        base_url = self._jellyfin_repo._base_url
        url = f"{base_url}/Users/AuthenticateByName"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": _EMBY_AUTH_HEADER.format(client_id = client_id),
        }
        body = {"Username": username, "Pw": password}

        try:
            async with httpx.AsyncClient(timeout = 15.0) as client:
                response = await client.post(url, headers = headers, json = body)
        except httpx.TimeoutException:
            raise ExternalServiceError("Jellyfin connection timed out")
        except httpx.ConnectError:
            raise ExternalServiceError("Could not connect to Jellyfin")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Jellyfin auth request failed: {e}")
            raise ExternalServiceError("Jellyfin authentication failed")

        if response.status_code == 401:
            raise AuthenticationError("Invalid Jellyfin username or password")
        if response.status_code == 403:
            raise AuthenticationError("This Jellyfin account does not have access")
        if response.status_code not in (200, 204):
            logger.debug(f"Jellyfin AuthenticateByName returned {response.status_code}")
            raise ExternalServiceError("Jellyfin authentication failed")

        try:
            data = response.json()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Failed to parse Jellyfin auth response: {e}")
            raise ExternalServiceError("Jellyfin returned an unexpected response")

        jellyfin_user = data.get("User", {})
        access_token = data.get("AccessToken", "")

        if not jellyfin_user.get("Id") or not access_token:
            raise ExternalServiceError("Jellyfin returned incomplete auth data")

        return {
            "jellyfin_user_id": jellyfin_user["Id"],
            "username": jellyfin_user.get("Name", username),
            "email": None,  # Jellyfin does not expose email via this endpoint
            "thumb": self._build_avatar_url(base_url, jellyfin_user),
            "access_token": access_token,
        }

    async def _find_or_create_user(self, profile: dict) -> UserRecord:
        jellyfin_user_id = profile["jellyfin_user_id"]
        username = profile["username"]
        email = profile["email"]
        thumb = profile["thumb"]
        access_token = profile["access_token"]

        provider_data = encrypt(json.dumps({"access_token": access_token}))

        existing_provider = await self._store.get_auth_provider("jellyfin", jellyfin_user_id)
        if existing_provider:
            await self._store.update_provider_data(existing_provider.id, provider_data)
            user = await self._store.get_user_by_id(existing_provider.user_id)
            if user is None:
                raise AuthenticationError("Linked account not found")
            return user

        if email:
            existing_user = await self._store.get_user_by_email(email)
            if existing_user:
                await self._store.create_auth_provider(
                    id = str(uuid.uuid4()),
                    user_id = existing_user.id,
                    provider = "jellyfin",
                    provider_uid = jellyfin_user_id,
                    provider_data = provider_data,
                )
                logger.info(f"Linked Jellyfin account to existing user: {existing_user.display_name} ({existing_user.id[:8]})")
                return existing_user

        user_id = str(uuid.uuid4())
        provider_id = str(uuid.uuid4())
        is_first = not await self._store.has_any_users()

        # Auto-derive a username from the Jellyfin Name (D3) so an SSO-only account
        # can later set a local password without a separate "choose username" step.
        # Retry on the unique-index race so two concurrent first-logins whose names
        # slug to the same base don't 500 (mirrors AuthStore._assign_unique_username).
        user = None
        for _attempt in range(20):
            derived_username, derived_display = await _derive_username(self._store, display_name = username)
            try:
                user = await self._store.create_user(
                    id = user_id,
                    display_name = username,
                    role = "admin" if is_first else "user",
                    email = email,
                    avatar_url = thumb,
                    username = derived_username,
                    username_display = derived_display,
                )
                break
            except sqlite3.IntegrityError:
                continue
        if user is None:
            raise AuthenticationError("Could not create an account from Jellyfin")
        await self._store.create_auth_provider(
            id = provider_id,
            user_id = user_id,
            provider = "jellyfin",
            provider_uid = jellyfin_user_id,
            provider_data = provider_data,
        )
        logger.info(f"New user created via Jellyfin: {username} ({user_id[:8]}) role={user.role}")
        return user

    @staticmethod
    def _build_avatar_url(base_url: str, jellyfin_user: dict) -> str | None:
        user_id = jellyfin_user.get("Id", "")
        has_image = (jellyfin_user.get("HasPrimaryImage") or jellyfin_user.get("PrimaryImageTag"))
        if user_id and has_image:
            return f"{base_url}/Users/{user_id}/Images/Primary"
        return None
