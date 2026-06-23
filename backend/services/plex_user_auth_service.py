"""Plex user authentication service"""

from __future__ import annotations

import json, logging, sqlite3, uuid

from core.exceptions import AuthenticationError, PlexApiError
from infrastructure.crypto import encrypt
from infrastructure.persistence.auth_store import AuthStore, UserRecord, _derive_username

logger = logging.getLogger(__name__)

_PRODUCT = "DroppedNeedle"


class PlexUserAuthService:
    def __init__(
        self,
        auth_store: AuthStore,
        plex_repository,
        preferences_service,
    ) -> None:
        self._store = auth_store
        self._plex_repo = plex_repository
        self._prefs = preferences_service

    def get_client_id(self) -> str:
        return self._prefs.get_or_create_setting("plex_client_id", lambda: str(uuid.uuid4()))

    async def create_login_pin(self) -> tuple[int, str]:
        client_id = self.get_client_id()
        try:
            pin = await self._plex_repo.create_oauth_pin(client_id)
        except PlexApiError as e:
            logger.error(f"Failed to create Plex OAuth pin: {e}")
            raise AuthenticationError("Could not start Plex authentication")

        auth_url = (
            f"https://app.plex.tv/auth#?"
            f"clientID={client_id}"
            f"&code={pin.code}"
            f"&context%5Bdevice%5D%5Bproduct%5D={_PRODUCT}"
        )
        return pin.id, auth_url

    async def poll_and_login(self, pin_id: int, user_agent: str | None = None) -> tuple[UserRecord, str] | None:
        client_id = self.get_client_id()
        auth_token = await self._plex_repo.poll_oauth_pin(pin_id, client_id)
        if not auth_token:
            return None

        profile = await self._get_user_profile(auth_token, client_id)

        machine_id = await self._get_server_machine_id()
        if machine_id:
            if not await self._check_server_membership(auth_token, client_id, machine_id):
                logger.warning(f"Plex login rejected: user {profile.get('uuid', '?')[:8]} not on server {machine_id[:8]}")
                raise AuthenticationError("Your Plex account does not have access to this server")

        user = await self._find_or_create_user(profile, auth_token)

        raw_token, token_hash = self._store.issue_token()
        await self._store.store_token(
            id = str(uuid.uuid4()),
            user_id = user.id,
            token_hash = token_hash,
            user_agent = user_agent,
        )
        await self._store.update_last_login(user.id)

        logger.info(f"Plex login: {user.display_name} ({user.id[:8]})")
        return user, raw_token

    async def _get_user_profile(self, auth_token: str, client_id: str) -> dict:
        try:
            profile = await self._plex_repo.get_account_profile(auth_token, client_id)
        except PlexApiError as e:
            logger.error(f"Failed to fetch Plex user profile: {e}")
            raise AuthenticationError("Could not verify Plex account")

        return {
            "uuid": profile.uuid,
            "email": profile.email or "",
            "display_name": profile.display_name,
            "thumb": profile.thumb,
            "auth_token": auth_token,
        }

    async def _check_server_membership(self, auth_token: str, client_id: str, machine_id: str) -> bool:
        try:
            server_ids = await self._plex_repo.get_account_server_ids(auth_token, client_id)
        except PlexApiError as e:
            logger.error(f"Failed to fetch Plex resources: {e}")
            raise AuthenticationError("Could not verify server access")

        return machine_id in server_ids

    async def _get_server_machine_id(self) -> str | None:
        try:
            plex_settings = self._prefs.get_plex_connection_raw()
            if not plex_settings.enabled:
                return None
            machine_id = await self._plex_repo.get_machine_identifier()
            return machine_id
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not get Plex server machine ID: {e}")
            return None

    async def _find_or_create_user(self, profile: dict, auth_token: str) -> UserRecord:
        plex_uid = profile["uuid"]
        email = profile["email"] or None
        name = profile["display_name"]
        thumb = profile["thumb"]

        provider_data = encrypt(json.dumps({"auth_token": auth_token}))

        existing_provider = await self._store.get_auth_provider("plex", plex_uid)
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
                    provider = "plex",
                    provider_uid = plex_uid,
                    provider_data = provider_data,
                )
                logger.info(f"Linked Plex account to existing user: {existing_user.display_name} ({existing_user.id[:8]})")
                return existing_user

        user_id = str(uuid.uuid4())
        provider_id = str(uuid.uuid4())
        is_first = not await self._store.has_any_users()

        # Auto-derive a username from the Plex display name (D3) so an SSO-only
        # account can later set a local password without choosing a username.
        # Retry on the unique-index race so two concurrent first-logins whose names
        # slug to the same base don't 500 (mirrors AuthStore._assign_unique_username).
        user = None
        for _attempt in range(20):
            derived_username, derived_display = await _derive_username(self._store, display_name = name)
            try:
                user = await self._store.create_user(
                    id = user_id,
                    display_name = name,
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
            raise AuthenticationError("Could not create an account from Plex")
        await self._store.create_auth_provider(
            id = provider_id,
            user_id = user_id,
            provider = "plex",
            provider_uid = plex_uid,
            provider_data = provider_data,
        )
        logger.info(f"New user created via Plex: {name} ({user_id[:8]}) role = {user.role}")
        return user
