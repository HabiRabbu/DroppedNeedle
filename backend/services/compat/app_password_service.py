"""App-password service: the single credential primitive for both compat shims.

One server-generated secret is stored Fernet-encrypted (recoverable, needed for
Subsonic ``t = md5(S + s)`` auth) plus a SHA-256 hash (O(1) lookup).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from uuid import uuid4

import msgspec

from core.exceptions import (
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
    SubsonicError,
)
from infrastructure.crypto import decrypt, encrypt
from infrastructure.persistence.app_password_store import (
    AppPasswordRow,
    AppPasswordStore,
)
from infrastructure.persistence.auth_store import AuthStore, UserRecord

logger = logging.getLogger(__name__)

MAX_ACTIVE_APP_PASSWORDS = 25


class AppPasswordView(msgspec.Struct):
    """Display-only DTO. Excludes both secret columns."""

    id: str
    name: str
    created_at: str
    last_used_at: str | None = None
    last_client: str | None = None


class AppPasswordRecord(msgspec.Struct):
    """Owner-facing record (no secrets); returned alongside the one-time plaintext."""

    id: str
    user_id: str
    name: str
    created_at: str
    last_used_at: str | None = None
    last_client: str | None = None


class AdminAppPasswordView(msgspec.Struct):
    """Admin-oversight DTO: one active app-password plus its owner. No secrets."""

    id: str
    user_id: str
    owner_username: str
    owner_display_name: str
    name: str
    created_at: str
    last_used_at: str | None = None
    last_client: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


class AppPasswordService:
    def __init__(self, store: AppPasswordStore, auth_store: AuthStore) -> None:
        self._store = store
        self._auth_store = auth_store
        self._bg_tasks: set[asyncio.Task] = set()

    async def create(self, user_id: str, name: str) -> tuple[AppPasswordRecord, str]:
        """Returns (record, plaintext); the plaintext is shown to the user once."""
        active = await self._store.count_active_by_user(user_id)
        if active >= MAX_ACTIVE_APP_PASSWORDS:
            raise ConflictError(
                f"App-password limit reached ({MAX_ACTIVE_APP_PASSWORDS}). "
                "Revoke one before creating another."
            )
        secret = secrets.token_urlsafe(24)
        row = AppPasswordRow(
            id=uuid4().hex,
            user_id=user_id,
            name=name.strip() or "App password",
            secret_sha256=_sha256(secret),
            secret_encrypted=encrypt(secret),
            created_at=_now_iso(),
        )
        await self._store.insert(row)
        logger.info(
            "Connect Apps audit: app-password created user=%s id=%s name=%r",
            user_id, row.id, row.name,
        )
        return self._to_record(row), secret

    async def list_for_user(self, user_id: str) -> list[AppPasswordView]:
        rows = await self._store.list_active_by_user(user_id)
        return [self._to_view(r) for r in rows]

    async def active_count(self, user_id: str) -> int:
        return await self._store.count_active_by_user(user_id)

    async def revoke(self, user_id: str, app_password_id: str) -> None:
        """Soft-revoke. Non-owner or unknown id raises PermissionDeniedError
        (route maps to 404 to avoid leaking)."""
        row = await self._store.get_by_id(app_password_id)
        if row is None or row.user_id != user_id:
            raise PermissionDeniedError("App-password not found")
        await self._store.revoke(app_password_id)
        logger.info(
            "Connect Apps audit: app-password revoked user=%s id=%s name=%r",
            user_id, row.id, row.name,
        )

    async def list_all_active_with_owners(self) -> list[AdminAppPasswordView]:
        """Admin oversight: every active app-password across all users, each
        enriched with its owner. Never returns a secret."""
        rows = await self._store.list_all_active()
        owners = await self._auth_store.get_users_by_ids(
            list({row.user_id for row in rows})
        )
        views: list[AdminAppPasswordView] = []
        for row in rows:
            owner = owners.get(row.user_id)
            if owner is None:
                # owner vanished mid-flight (FK cascade); skip rather than show a ghost
                continue
            views.append(
                AdminAppPasswordView(
                    id=row.id,
                    user_id=row.user_id,
                    owner_username=(
                        owner.username_display or owner.username or owner.display_name
                    ),
                    owner_display_name=owner.display_name,
                    name=row.name,
                    created_at=row.created_at,
                    last_used_at=row.last_used_at,
                    last_client=row.last_client,
                )
            )
        return views

    async def admin_revoke(self, admin_user_id: str, app_password_id: str) -> None:
        """Admin revokes ANY user's app-password (no ownership check). Missing or
        already-revoked id raises ResourceNotFoundError (route -> 404). Distinct
        from the owner-scoped revoke, which cannot act on another user's row."""
        row = await self._store.get_by_id(app_password_id)
        if row is None or row.revoked:
            raise ResourceNotFoundError("App-password not found")
        await self._store.revoke(app_password_id)
        logger.info(
            "Connect Apps audit: app-password admin-revoked admin=%s owner=%s id=%s name=%r",
            admin_user_id, row.user_id, row.id, row.name,
        )

    async def verify_token(self, token: str) -> UserRecord | None:
        """SHA-256(token) -> active row -> UserRecord. None on miss; never raises.
        Key-rotation safe (no decryption)."""
        if not token:
            return None
        row = await self._store.get_active_by_sha256(_sha256(token))
        if row is None:
            return None
        user = await self._auth_store.get_user_by_id(row.user_id)
        if user is None:
            return None
        self._spawn_touch(row.secret_sha256, None)
        return user

    async def verify_subsonic(
        self,
        *,
        u: str | None,
        t: str | None,
        s: str | None,
        p: str | None,
        api_key: str | None,
        client: str | None,
    ) -> UserRecord:
        """All three Subsonic auth schemes. Raises SubsonicError(code) on failure."""
        if api_key and u:
            raise SubsonicError(43)
        if api_key:
            user = await self.verify_token(api_key)
            if user is None:
                raise SubsonicError(44)
            return user
        if not u:
            raise SubsonicError(10)
        user = await self._auth_store.get_user_by_username(u.strip().lower())
        if user is None:
            raise SubsonicError(40)
        pws = await self._store.list_active_by_user(user.id)

        if t and s:
            target = t.lower()
            for pw in pws:
                plaintext, was_legacy = decrypt(pw.secret_encrypted)
                if was_legacy:
                    logger.warning(
                        "App-password %s secret is unrecoverable (Fernet key "
                        "rotation?); skipping for t/s auth",
                        pw.id,
                    )
                    continue
                if hmac.compare_digest(_md5(plaintext + s), target):
                    self._spawn_touch(pw.secret_sha256, client)
                    return user
            raise SubsonicError(40)

        if p is not None:
            secret = _decode_subsonic_password(p)
            row = await self._store.get_active_by_sha256(_sha256(secret))
            if row is not None and row.user_id == user.id:
                self._spawn_touch(row.secret_sha256, client)
                return user
            raise SubsonicError(40)

        raise SubsonicError(10)

    async def authenticate_username_password(
        self, username: str, password: str, client: str | None
    ) -> UserRecord:
        """Jellyfin AuthenticateByName. Raises PermissionDeniedError on a bad
        credential (the detector maps to 401)."""
        if not password:
            raise PermissionDeniedError("Invalid username or app-password")
        row = await self._store.get_active_by_sha256(_sha256(password))
        if row is not None:
            user = await self._auth_store.get_user_by_id(row.user_id)
            if user is not None and (user.username or "") == username.strip().lower():
                self._spawn_touch(row.secret_sha256, client)
                return user
        raise PermissionDeniedError("Invalid username or app-password")

    async def touch(self, secret_sha256: str, client: str | None) -> None:
        try:
            await self._store.touch(
                secret_sha256, last_used_at=_now_iso(), last_client=client
            )
        except Exception:  # noqa: BLE001 - best-effort; never fail auth on this
            logger.debug("app-password touch failed", exc_info=True)

    def _spawn_touch(self, secret_sha256: str, client: str | None) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.touch(secret_sha256, client))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    @staticmethod
    def _to_record(row: AppPasswordRow) -> AppPasswordRecord:
        return AppPasswordRecord(
            id=row.id,
            user_id=row.user_id,
            name=row.name,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            last_client=row.last_client,
        )

    @staticmethod
    def _to_view(row: AppPasswordRow) -> AppPasswordView:
        return AppPasswordView(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            last_client=row.last_client,
        )


def _decode_subsonic_password(p: str) -> str:
    """Decode the Subsonic ``p`` param: ``enc:<hex>`` decodes to utf-8, else raw."""
    if p.startswith("enc:"):
        try:
            return bytes.fromhex(p[4:]).decode("utf-8")
        except ValueError:
            return p
    return p
