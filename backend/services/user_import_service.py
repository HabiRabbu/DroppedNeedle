"""Admin import of users from Jellyfin/Plex (Phase 6, D5).

Enumerates accounts from the shared media server and pre-provisions DroppedNeedle
accounts: each import creates an auth_users row (role="user") plus a pre-linked
auth_providers row (provider_data=None - a login identity, not a credential
store). On the user's first SSO login the existing _find_or_create_user matches
the pre-seeded provider_uid, so no admin-set password is needed.

The join key (provider_uid) MUST equal exactly what the live login produces:
- Jellyfin: the user Id from GET /Users.
- Plex: the account uuid (== account.uuid from get_token_details; see
  plex_API_NOTES.md / AMU-7).
"""

from __future__ import annotations

import logging
import sqlite3
import uuid

import msgspec

from core.exceptions import RegistrationError
from infrastructure.persistence.auth_store import (
    AuthStore,
    UserRecord,
    _derive_username,
)

logger = logging.getLogger(__name__)


class ImportCandidate(msgspec.Struct, frozen=True):
    provider: str
    provider_uid: str
    display_name: str
    avatar_url: str | None = None
    email: str | None = None
    already_imported: bool = False


class ImportResult(msgspec.Struct, frozen=True):
    imported: list[UserRecord]
    linked: list[UserRecord]
    skipped: list[str]


class UserImportService:
    def __init__(
        self,
        auth_store: AuthStore,
        jellyfin_repository,
        plex_repository,
        preferences_service,
    ) -> None:
        self._store = auth_store
        self._jellyfin = jellyfin_repository
        self._plex = plex_repository
        self._prefs = preferences_service

    async def list_jellyfin_users(self) -> list[ImportCandidate]:
        users = await self._jellyfin.get_users()
        base_url = (self._prefs.get_jellyfin_connection().jellyfin_url or "").rstrip("/")
        candidates: list[ImportCandidate] = []
        for user in users:
            existing = await self._store.get_auth_provider("jellyfin", user.id)
            # Best-effort picker thumbnail; GET /Users drops HasPrimaryImage, so we
            # cannot guard it here - the UI falls back to the placeholder on a 404,
            # and import_users does NOT persist this URL (see _import_one).
            avatar_url = f"{base_url}/Users/{user.id}/Images/Primary" if base_url else None
            candidates.append(
                ImportCandidate(
                    provider="jellyfin",
                    provider_uid=user.id,
                    display_name=user.name,
                    avatar_url=avatar_url,
                    email=None,  # Jellyfin does not expose email
                    already_imported=existing is not None,
                )
            )
        return candidates

    async def list_plex_users(self) -> list[ImportCandidate]:
        accounts = await self._plex.enumerate_users()
        candidates: list[ImportCandidate] = []
        for account in accounts:
            existing = await self._store.get_auth_provider("plex", account.uuid)
            candidates.append(
                ImportCandidate(
                    provider="plex",
                    provider_uid=account.uuid,
                    display_name=account.title or account.username,
                    avatar_url=account.thumb,
                    email=account.email,
                    already_imported=existing is not None,
                )
            )
        return candidates

    async def import_users(self, provider: str, provider_uids: list[str]) -> ImportResult:
        # Re-fetch the candidates server-side - never trust client-supplied
        # display names/emails. Keyed by provider_uid for lookup.
        if provider == "jellyfin":
            catalog = {c.provider_uid: c for c in await self.list_jellyfin_users()}
        elif provider == "plex":
            catalog = {c.provider_uid: c for c in await self.list_plex_users()}
        else:
            raise RegistrationError(f"Unsupported import provider: {provider}")

        imported: list[UserRecord] = []
        linked: list[UserRecord] = []
        skipped: list[str] = []

        for uid in provider_uids:
            candidate = catalog.get(uid)
            if candidate is None:
                skipped.append(uid)
                continue
            try:
                status, user = await self._import_one(provider, candidate)
            except RegistrationError:
                # Un-de-dupable username - surface as 409 (route maps it).
                raise
            except Exception as exc:  # noqa: BLE001 - one bad uid must not abort the batch
                logger.warning("Import failed for %s uid %s: %s", provider, uid[:8], exc)
                skipped.append(uid)
                continue
            if status == "imported" and user is not None:
                imported.append(user)
            elif status == "linked" and user is not None:
                linked.append(user)
            else:
                skipped.append(uid)

        logger.info(
            "User import (%s): %d imported, %d linked, %d skipped",
            provider,
            len(imported),
            len(linked),
            len(skipped),
        )
        return ImportResult(imported=imported, linked=linked, skipped=skipped)

    async def _import_one(
        self, provider: str, candidate: ImportCandidate
    ) -> tuple[str, UserRecord | None]:
        uid = candidate.provider_uid

        # Idempotency: already linked -> skip (never duplicate).
        existing = await self._store.get_auth_provider(provider, uid)
        if existing is not None:
            return ("skipped", None)

        # L1: email collision -> LINK to the existing user (do not create a new
        # one, do not touch their email/display_name/username). They then log in
        # via this provider into their existing account.
        if candidate.email:
            existing_user = await self._store.get_user_by_email(candidate.email)
            if existing_user is not None:
                await self._store.create_auth_provider(
                    id=str(uuid.uuid4()),
                    user_id=existing_user.id,
                    provider=provider,
                    provider_uid=uid,
                    provider_data=None,
                )
                return ("linked", existing_user)

        # New user. Plex thumbs are real fetched URLs; the Jellyfin avatar is an
        # unguarded constructed URL, so we do not persist it (AMU-7 open risk).
        avatar_url = candidate.avatar_url if provider == "plex" else None
        user_id = str(uuid.uuid4())

        # Derive a unique username (Phase 1 helper). Retry on the unique-index
        # race so the IntegrityError never surfaces (mirrors the SSO services).
        user: UserRecord | None = None
        for _attempt in range(20):
            derived_username, derived_display = await _derive_username(
                self._store,
                email=candidate.email,
                display_name=candidate.display_name,
            )
            try:
                user = await self._store.create_user(
                    id=user_id,
                    display_name=candidate.display_name,
                    role="user",  # forced - never set from the request body (D5)
                    email=candidate.email,
                    avatar_url=avatar_url,
                    username=derived_username,
                    username_display=derived_display,
                )
                break
            except sqlite3.IntegrityError:
                continue
        if user is None:
            raise RegistrationError(
                f"Could not derive a unique username for {provider} user"
            )

        # Pre-linked provider row: provider_data=None (AMU-3 - login identity, not
        # a credential store; the real token is captured on first SSO login).
        await self._store.create_auth_provider(
            id=str(uuid.uuid4()),
            user_id=user.id,
            provider=provider,
            provider_uid=uid,
            provider_data=None,
        )
        return ("imported", user)
