"""T0.3 - AppPasswordService: schemes, cap, revocation, ownership, crypto."""

import hashlib

import pytest
from cryptography.fernet import Fernet

import infrastructure.crypto as crypto
from core.exceptions import (
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
    SubsonicError,
)
from infrastructure.crypto import encrypt
from infrastructure.persistence.app_password_store import (
    AppPasswordRow,
    AppPasswordStore,
)
from services.compat.app_password_service import (
    MAX_ACTIVE_APP_PASSWORDS,
    AppPasswordService,
    AppPasswordView,
    _now_iso,
)

pytestmark = pytest.mark.asyncio


def _sha256(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


async def _seed_secret(
    store: AppPasswordStore, user_id: str, secret: str, name: str = "fixed"
) -> AppPasswordRow:
    row = AppPasswordRow(
        id=f"ap-{user_id}-{name}",
        user_id=user_id,
        name=name,
        secret_sha256=_sha256(secret),
        secret_encrypted=encrypt(secret),
        created_at=_now_iso(),
    )
    await store.insert(row)
    return row


# ----- Subsonic schemes -----

async def test_token_scheme_spec_vector(app_password_service, app_password_store):
    # password "sesame", salt "c19b2d" -> md5 == 26719a1196d2a940705a59634eb18eab
    await _seed_secret(app_password_store, "user-alice", "sesame")
    user = await app_password_service.verify_subsonic(
        u="alice", t="26719a1196d2a940705a59634eb18eab", s="c19b2d",
        p=None, api_key=None, client="pytest",
    )
    assert user.id == "user-alice"


async def test_token_scheme_wrong_t_is_40(app_password_service, app_password_store):
    await _seed_secret(app_password_store, "user-alice", "sesame")
    with pytest.raises(SubsonicError) as e:
        await app_password_service.verify_subsonic(
            u="alice", t="deadbeef" * 4, s="c19b2d",
            p=None, api_key=None, client="pytest",
        )
    assert e.value.code == 40


async def test_enc_password_hex_decode(app_password_service, app_password_store):
    await _seed_secret(app_password_store, "user-alice", "sesame")
    user = await app_password_service.verify_subsonic(
        u="alice", t=None, s=None, p="enc:736573616d65", api_key=None, client="x"
    )
    assert user.id == "user-alice"


async def test_plaintext_password(app_password_service, app_password_store):
    await _seed_secret(app_password_store, "user-alice", "sesame")
    user = await app_password_service.verify_subsonic(
        u="alice", t=None, s=None, p="sesame", api_key=None, client="x"
    )
    assert user.id == "user-alice"


async def test_apikey_lookup_without_u(app_password_service):
    record, secret = await app_password_service.create("user-bob", "Feishin")
    user = await app_password_service.verify_subsonic(
        u=None, t=None, s=None, p=None, api_key=secret, client="feishin"
    )
    assert user.id == "user-bob"


async def test_apikey_and_u_conflict_is_43(app_password_service):
    _, secret = await app_password_service.create("user-bob", "Feishin")
    with pytest.raises(SubsonicError) as e:
        await app_password_service.verify_subsonic(
            u="bob", t=None, s=None, p=None, api_key=secret, client="x"
        )
    assert e.value.code == 43


async def test_invalid_apikey_is_44(app_password_service):
    with pytest.raises(SubsonicError) as e:
        await app_password_service.verify_subsonic(
            u=None, t=None, s=None, p=None, api_key="not-a-real-key", client="x"
        )
    assert e.value.code == 44


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("u", "u" * 257, 40),
        ("t", "t" * 129, 40),
        ("s", "s" * 129, 40),
        ("p", "p" * 2053, 40),
        ("api_key", "k" * 1025, 44),
        ("client", "c" * 257, 10),
    ],
)
async def test_subsonic_auth_fields_are_bounded_before_lookup(
    app_password_service, field, value, expected_code
):
    values = {
        "u": "alice",
        "t": None,
        "s": None,
        "p": "wrong",
        "api_key": None,
        "client": "client",
    }
    values[field] = value
    if field == "api_key":
        values["u"] = None
        values["p"] = None
    with pytest.raises(SubsonicError) as exc:
        await app_password_service.verify_subsonic(**values)
    assert exc.value.code == expected_code


async def test_jellyfin_auth_fields_are_bounded(app_password_service):
    with pytest.raises(PermissionDeniedError):
        await app_password_service.authenticate_username_password(
            "u" * 257, "p" * 1025, "c" * 257
        )


async def test_missing_required_param_is_10(app_password_service, app_password_store):
    await _seed_secret(app_password_store, "user-alice", "sesame")
    # only u, no t/s/p/apiKey -> 10
    with pytest.raises(SubsonicError) as e:
        await app_password_service.verify_subsonic(
            u="alice", t=None, s=None, p=None, api_key=None, client="x"
        )
    assert e.value.code == 10
    # no u at all on the non-apiKey path -> 10
    with pytest.raises(SubsonicError) as e2:
        await app_password_service.verify_subsonic(
            u=None, t="x", s="y", p=None, api_key=None, client="x"
        )
    assert e2.value.code == 10


async def test_unknown_user_is_40(app_password_service):
    with pytest.raises(SubsonicError) as e:
        await app_password_service.verify_subsonic(
            u="nobody", t=None, s=None, p="whatever", api_key=None, client="x"
        )
    assert e.value.code == 40


# ----- create / view / cap -----

async def test_create_returns_secret_once_and_stores_hash_not_plaintext(
    app_password_service, app_password_store
):
    record, secret = await app_password_service.create("user-alice", "Symfonium")
    row = await app_password_store.get_by_id(record.id)
    assert row is not None
    assert row.secret_sha256 == _sha256(secret)
    assert row.secret_encrypted != secret
    # the owner-facing record carries no secret columns
    assert not hasattr(record, "secret_sha256")
    assert not hasattr(record, "secret_encrypted")


async def test_app_password_view_excludes_secret_columns(app_password_service):
    await app_password_service.create("user-alice", "Finamp")
    views = await app_password_service.list_for_user("user-alice")
    assert len(views) == 1
    import msgspec

    keys = set(msgspec.to_builtins(views[0]).keys())
    assert keys == {"id", "name", "created_at", "last_used_at", "last_client"}
    assert isinstance(views[0], AppPasswordView)


async def test_create_at_cap_raises_conflicterror(app_password_service):
    for i in range(MAX_ACTIVE_APP_PASSWORDS):
        await app_password_service.create("user-alice", f"client-{i}")
    assert await app_password_service.active_count("user-alice") == MAX_ACTIVE_APP_PASSWORDS
    with pytest.raises(ConflictError):
        await app_password_service.create("user-alice", "one-too-many")


# ----- revocation / ownership -----

async def test_revoke_kills_all_schemes(app_password_service, app_password_store):
    record, secret = await app_password_service.create("user-alice", "AllSchemes")
    # prove all schemes work first
    assert (await app_password_service.verify_token(secret)).id == "user-alice"
    assert (
        await app_password_service.verify_subsonic(
            u="alice", t=None, s=None, p=secret, api_key=None, client="x"
        )
    ).id == "user-alice"
    assert (
        await app_password_service.authenticate_username_password("alice", secret, "x")
    ).id == "user-alice"

    await app_password_service.revoke("user-alice", record.id)

    assert await app_password_service.verify_token(secret) is None
    with pytest.raises(SubsonicError):
        await app_password_service.verify_subsonic(
            u="alice", t=None, s=None, p=secret, api_key=None, client="x"
        )
    with pytest.raises(SubsonicError):
        await app_password_service.verify_subsonic(
            u=None, t=None, s=None, p=None, api_key=secret, client="x"
        )
    with pytest.raises(PermissionDeniedError):
        await app_password_service.authenticate_username_password("alice", secret, "x")


async def test_revoke_enforces_ownership(app_password_service):
    record, _ = await app_password_service.create("user-alice", "Alice device")
    with pytest.raises(PermissionDeniedError):
        await app_password_service.revoke("user-bob", record.id)


async def test_verify_token_ignores_revoked_rows(app_password_service):
    record, secret = await app_password_service.create("user-alice", "X")
    await app_password_service.revoke("user-alice", record.id)
    assert await app_password_service.verify_token(secret) is None


# ----- Jellyfin login -----

async def test_authenticate_username_password_round_trip(app_password_service):
    _, secret = await app_password_service.create("user-bob", "Finamp")
    user = await app_password_service.authenticate_username_password("bob", secret, "finamp")
    assert user.id == "user-bob"
    # token issued = secret; resolves back via verify_token
    assert (await app_password_service.verify_token(secret)).id == "user-bob"


async def test_authenticate_bad_pw_raises(app_password_service):
    with pytest.raises(PermissionDeniedError):
        await app_password_service.authenticate_username_password("bob", "wrong", "x")


# ----- crypto failure degrades, never 500 -----

async def test_decrypt_failure_returns_normal_auth_error(
    app_password_service, app_password_store, caplog, monkeypatch
):
    await _seed_secret(app_password_store, "user-alice", "sesame")
    # rotate the Fernet key so the stored ciphertext can no longer be decrypted
    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
    with caplog.at_level("WARNING"):
        with pytest.raises(SubsonicError) as e:
            await app_password_service.verify_subsonic(
                u="alice", t="26719a1196d2a940705a59634eb18eab", s="c19b2d",
                p=None, api_key=None, client="x",
            )
    assert e.value.code == 40  # not a 500
    assert any("unrecoverable" in r.message.lower() for r in caplog.records)


# ----- admin oversight (roster + admin revoke) -----

async def test_list_all_active_with_owners_enriches_and_hides_secrets(
    app_password_service,
):
    import msgspec

    await app_password_service.create("user-alice", "Alice phone")
    await app_password_service.create("user-bob", "Bob tablet")
    views = await app_password_service.list_all_active_with_owners()
    by_user = {v.user_id: v for v in views}
    assert set(by_user) == {"user-alice", "user-bob"}
    assert by_user["user-alice"].owner_username == "alice"
    assert by_user["user-alice"].owner_display_name == "Alice"
    keys = set(msgspec.to_builtins(views[0]).keys())
    assert "secret_sha256" not in keys and "secret_encrypted" not in keys


async def test_list_all_active_excludes_revoked(app_password_service):
    gone, _ = await app_password_service.create("user-alice", "gone")
    await app_password_service.revoke("user-alice", gone.id)
    await app_password_service.create("user-alice", "kept")
    views = await app_password_service.list_all_active_with_owners()
    assert [v.name for v in views] == ["kept"]


async def test_admin_roster_owner_lookup_not_truncated_beyond_100_users(
    app_password_service, auth_store
):
    # Create well past list_users' default 100-row window; the LAST-created user
    # (outside that window) gets an app-password. A truncating owner lookup would
    # silently drop it - this asserts the bulk get_users_by_ids path resolves it.
    for i in range(130):
        await auth_store.create_user(
            id=f"bulk-{i:03d}", display_name=f"User {i}", role="user",
            username=f"bulk{i}",
        )
    await app_password_service.create("bulk-129", "late joiner")
    views = await app_password_service.list_all_active_with_owners()
    late = [v for v in views if v.user_id == "bulk-129"]
    assert len(late) == 1
    assert late[0].owner_username == "bulk129"  # owner resolved, not dropped


async def test_admin_revoke_kills_any_users_credential(app_password_service):
    record, secret = await app_password_service.create("user-alice", "Alice phone")
    # a different admin id revokes alice's password (no ownership relationship)
    await app_password_service.admin_revoke("user-admin", record.id)
    assert await app_password_service.verify_token(secret) is None


async def test_admin_revoke_unknown_id_raises_not_found(app_password_service):
    with pytest.raises(ResourceNotFoundError):
        await app_password_service.admin_revoke("user-admin", "does-not-exist")


async def test_admin_revoke_already_revoked_raises_not_found(app_password_service):
    record, _ = await app_password_service.create("user-alice", "x")
    await app_password_service.admin_revoke("user-admin", record.id)
    with pytest.raises(ResourceNotFoundError):
        await app_password_service.admin_revoke("user-admin", record.id)


async def test_owner_username_uses_display_casing_then_falls_back(
    app_password_service, auth_store
):
    # username_display (preferred casing) wins over the lowercased username
    await auth_store.create_user(
        id="user-cased", display_name="Cased User", role="user",
        username="casey", username_display="CaseY",
    )
    # no username at all (e.g. an SSO-provisioned account) -> fall back to display_name,
    # never None (owner_username is a non-optional field)
    await auth_store.create_user(
        id="user-nouname", display_name="No Username", role="user",
    )
    await app_password_service.create("user-cased", "c")
    await app_password_service.create("user-nouname", "n")
    views = {v.user_id: v for v in await app_password_service.list_all_active_with_owners()}
    assert views["user-cased"].owner_username == "CaseY"
    assert views["user-nouname"].owner_username == "No Username"
    assert views["user-nouname"].owner_display_name == "No Username"
