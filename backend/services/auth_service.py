"""Auth service: local login/registration, token lifecycle, setup."""

from __future__ import annotations

import asyncio, hashlib, httpx, logging, os, uuid, json
import bcrypt as _bcrypt

from core.dependencies.cache_providers import get_preferences_service
from core.exceptions import AuthenticationError, RegistrationError
from infrastructure.persistence.auth_store import AuthStore, TokenRecord, UserRecord

logger = logging.getLogger(__name__)

_PW_KEY = "password_hash"


class AuthService:
    def __init__(self, auth_store: AuthStore) -> None:
        self._store = auth_store

    async def is_setup_required(self) -> bool:
        return not await self._store.has_any_users()

    async def create_first_admin(
        self,
        *,
        display_name: str,
        email: str,
        password: str,
        user_agent: str | None = None,
    ) -> tuple[UserRecord, str]:
        if not await self.is_setup_required():
            raise RegistrationError("Setup has already been completed")

        _validate_password(password)
        await _check_hibp(password)
        email = email.lower().strip()
        _validate_email(email)

        user_id = _new_id()
        provider_id = _new_id()

        user = await self._store.create_user(
            id = user_id,
            display_name = display_name.strip(),
            role = "admin",
            email = email,
        )

        await self._store.create_auth_provider(
            id = provider_id,
            user_id = user_id,
            provider = "local",
            provider_uid = email,
            provider_data = _make_local_data(password),
        )

        raw_token = await self._issue_session(user_id, user_agent = user_agent)
        await self._store.update_last_login(user_id)

        logger.info(f"First admin account created: {display_name} ({user_id[:8]})")
        return user, raw_token

    async def admin_create_user(
        self,
        *,
        display_name: str,
        email: str,
        password: str,
        role: str = "user",
    ) -> UserRecord:
        if role not in ("admin", "trusted", "user"):
            raise RegistrationError(f"Invalid role: {role}")
        _validate_password(password)
        await _check_hibp(password)
        email = email.lower().strip()
        _validate_email(email)

        existing = await self._store.get_user_by_email(email)
        if existing is not None:
            raise RegistrationError("Could not create user")

        user_id = _new_id()
        provider_id = _new_id()

        user = await self._store.create_user(
            id = user_id,
            display_name = display_name.strip(),
            role = role,
            email = email,
        )

        await self._store.create_auth_provider(
            id = provider_id,
            user_id = user_id,
            provider = "local",
            provider_uid = email,
            provider_data = _make_local_data(password),
        )

        logger.info(f"Admin created user: {display_name} ({user_id[:8]}) role: {role}")
        return user

    async def login_local(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
    ) -> tuple[UserRecord, str]:
        email = email.lower().strip()

        provider = await self._store.get_auth_provider("local", email)
        if provider is None:
            # Don't reveal whether the email exists
            _dummy_verify()
            raise AuthenticationError("Invalid email or password")

        if not _verify_password(password, provider.provider_data or ""):
            raise AuthenticationError("Invalid email or password")

        user = await self._store.get_user_by_id(provider.user_id)
        if user is None:
            raise AuthenticationError("Invalid email or password")

        raw_token = await self._issue_session(provider.user_id, user_agent = user_agent)
        await self._store.update_last_login(provider.user_id)

        logger.info(f"Local login: {user.display_name} ({user.id[:8]})")
        return user, raw_token

    async def verify_token(self, raw_token: str) -> tuple[UserRecord, TokenRecord] | None:
        token = await self._store.verify_token(raw_token)
        if token is None:
            return None

        user = await self._store.get_user_by_id(token.user_id)
        if user is None:
            return None

        try:
            await self._store.touch_token(token.id)
        except Exception:  # noqa: BLE001
            pass

        return user, token

    async def logout(self, raw_token: str) -> None:
        token = await self._store.verify_token(raw_token)
        if token is not None:
            await self._store.revoke_token(token.id)

    async def logout_all(self, user_id: str, *, except_raw_token: str | None = None, except_token_id: str | None = None) -> None:
        if except_token_id is None and except_raw_token:
            current = await self._store.verify_token(except_raw_token)
            if current:
                except_token_id = current.id

        await self._store.revoke_all_tokens_for_user(user_id, except_token_id = except_token_id)

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[UserRecord]:
        return await self._store.list_users(limit = limit, offset = offset)

    async def count_users(self) -> int:
        return await self._store.count_users()

    async def set_role(self, user_id: str, role: str, *, requesting_user_id: str | None = None) -> None:
        if role not in ("admin", "trusted", "user"):
            raise AuthenticationError(f"Invalid role: {role}")
        if requesting_user_id is not None and requesting_user_id == user_id and role != "admin":
            raise AuthenticationError("Cannot remove your own admin privileges")
        target = await self._store.get_user_by_id(user_id)
        if target is not None and target.role == "admin" and role != "admin":
            admin_count = await self._store.count_users_by_role("admin")
            if admin_count <= 1:
                raise AuthenticationError("Cannot remove the last admin account")
        await self._store.update_user_role(user_id, role)

    async def delete_user(self, user_id: str, *, requesting_user_id: str) -> None:
        if requesting_user_id == user_id:
            raise AuthenticationError("Cannot delete your own account")
        target = await self._store.get_user_by_id(user_id)
        if target is None:
            raise AuthenticationError("User not found")
        if target.role == "admin":
            admin_count = await self._store.count_users_by_role("admin")
            if admin_count <= 1:
                raise AuthenticationError("Cannot delete the last admin account")
        await self._store.delete_user(user_id)

    async def get_provider_names_for_users(self, user_ids: list[str]) -> dict[str, list[str]]:
        return await self._store.list_provider_names_for_users(user_ids)

    async def revoke_user_sessions(self, user_id: str) -> None:
        await self._store.revoke_all_tokens_for_user(user_id)

    async def list_sessions(self, user_id: str) -> list[TokenRecord]:
        return await self._store.list_tokens_for_user(user_id)

    async def revoke_session(self, token_id: str, requesting_user_id: str) -> None:
        tokens = await self._store.list_tokens_for_user(requesting_user_id)
        owned = any(token.id == token_id for token in tokens)
        if not owned:
            raise AuthenticationError("Cannot revoke a session that does not belong to you")
        await self._store.revoke_token(token_id)

    async def cleanup_expired_tokens(self) -> int:
        return await self._store.cleanup_expired_tokens()

    async def _issue_session(self, user_id: str, *, user_agent: str | None = None) -> str:
        raw_token, token_hash = self._store.issue_token()
        await self._store.store_token(
            id = _new_id(),
            user_id = user_id,
            token_hash = token_hash,
            user_agent = user_agent,
        )
        return raw_token


def _new_id() -> str:
    return str(uuid.uuid4())


def _make_local_data(password: str) -> str:
    """Return a JSON-safe string holding the bcrypt hash.

    External tokens (Plex, Jellyfin) will use encrypted JSON in provider_data.
    For local accounts we just store the bcrypt hash directly, bcrypt is
    already a one-way function designed for password storage, encryption
    on top adds no meaningful security benefit.
    """
    hashed = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    return json.dumps({_PW_KEY: hashed})


def _verify_password(password: str, provider_data: str) -> bool:
    try:
        data = json.loads(provider_data)
        stored_hash = data.get(_PW_KEY, "")
        return _bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:  # noqa: BLE001
        return False


def _dummy_verify() -> None:
    """Run a bcrypt verify against a dummy hash to prevent timing attacks
    that would reveal whether an email address is registered."""
    try:
        _bcrypt.checkpw(
            b"dummy",
            b"$2b$12$KIXqKFZb9VpLJ3DFnvOHEeGjF1f8L4RkX5p7Z2YqM9U3J0BwN1C6K",
        )
    except Exception:  # noqa: BLE001
        pass


def _validate_password(password: str) -> None:
    if len(password) < 12:
        raise RegistrationError("Password must be at least 12 characters")


def _validate_email(email: str) -> None:
    if not email or "@" not in email or len(email) < 5:
        raise RegistrationError("Invalid email address")


async def _check_hibp(password: str) -> None:
    """Reject passwords found in the Have I Been Pwned breach corpus.

    Priority:
      1. Local file (if hibp_local_path is set and the file exists), no outbound calls.
      2. api.pwnedpasswords.com range API, free, no key required, uses k-anonymity
         so only the first 5 hex chars of the SHA-1 hash leave the server.
         Note: this is separate from the paid haveibeenpwned.com notification API.
    If hibp_check is False, the function returns immediately.
    Both paths fail open on error so a missing file or unreachable service never
    blocks account creation.
    """
    sec = get_preferences_service().get_security_settings()

    if not sec.hibp_check:
        return

    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()

    if sec.hibp_local_path:
        path = sec.hibp_local_path.strip()
        if os.path.isfile(path):
            found = await asyncio.to_thread(_search_hibp_file, sha1, path)
            if found:
                raise RegistrationError(
                    "This password has appeared in a known data breach. Please choose a different password."
                )
            return
        else:
            logger.warning("HIBP local path configured but file not found. Skipping breach check")
            return  # user opted out of API calls; fail open

    # --- api.pwnedpasswords.com range API (k-anonymity, free, no key required) ---
    # Distinct from the paid haveibeenpwned.com notification/lookup API.
    # Only the first 5 hex chars of the SHA-1 hash are transmitted.
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                headers={"Add-Padding": "true"},
            )
        if resp.status_code != 200:
            return  # fail open

        for line in resp.text.splitlines():
            if ":" not in line:
                continue
            line_suffix, _ = line.split(":", 1)
            if line_suffix.upper() == suffix:
                raise RegistrationError(
                    "This password has appeared in a known data breach. Please choose a different password."
                )
    except RegistrationError:
        raise
    except Exception:  # noqa: BLE001
        logger.warning("pwnedpasswords.com range check failed (network error). Proceeding without breach check")


def _search_hibp_file(sha1: str, path: str) -> bool:
    """Binary-search a sorted HIBP 'Pwned Passwords (ordered by hash)' text file.

    File format (official HIBP download, hash-ordered):
        ABCDEF...40HEX:COUNT\\r\\n   (one entry per line, sorted ascending)

    O(log N) disk seeks, typically ~30 seeks regardless of file size.
    """
    try:
        file_size = os.path.getsize(path)
        if file_size == 0:
            return False

        with open(path, "rb") as fh:
            low: int = 0
            high: int = file_size

            while low < high:
                mid = (low + high) // 2
                fh.seek(mid)

                # Skip the partial line we landed in the middle of.
                if mid > 0:
                    fh.readline()

                line_start = fh.tell()
                if line_start >= high:
                    break

                raw = fh.readline()
                if not raw:
                    break

                text = raw.decode("ascii", errors="ignore").rstrip("\r\n")
                if not text or ":" not in text:
                    break

                line_hash = text.split(":", 1)[0].upper()

                if line_hash == sha1:
                    return True
                elif line_hash < sha1:
                    # Target is after this line.
                    new_low = fh.tell()
                    if new_low <= low:
                        break  # no progress, file may be malformed
                    low = new_low
                else:
                    # Target (if present) is before this line's position.
                    if mid <= low:
                        break
                    high = mid

        return False
    except OSError:
        return False
