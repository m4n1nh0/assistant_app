import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession as _AuthAsyncSession
from ..core.security import (
    account_token,
    create_token,
    decode_token,
    get_current_user,
    hash_secret,
    require_admin,
    verify_secret,
)
from ..core.config import get_settings
from ..core.database import (
    AssistantProfileModel,
    TutorModel,
    UserModel,
    get_db as _get_auth_db,
    seed_admin_notification_config,
)
from ..models.schemas import (
    LoginRequest, RegisterRequest, ChangePasswordRequest,
    AdminInviteRequest, AdminInviteResponse, AdminUserResponse,
    AuthResponse, AuthStatusResponse, RegistrationTokenResponse,
)
from ..services.registration_invite_service import (
    RegistrationDeliveryError,
    RegistrationTokenCooldownError,
    issue_registration_token,
    lock_registration_invite,
    mask_email,
    registration_delivery_configured,
    brevo_api_diagnostic,
)

router_auth = APIRouter(prefix="/auth", tags=["Auth"])
settings = get_settings()


@router_auth.get("/status", response_model=AuthStatusResponse)
async def auth_status(db: _AuthAsyncSession = Depends(_get_auth_db)):
    count = (await db.execute(select(func.count()).select_from(UserModel))).scalar_one()
    needs_setup = count == 0
    requires_token = needs_setup and settings.registration_invite_required
    return AuthStatusResponse(
        needs_setup=needs_setup,
        invite_registration_enabled=True,
        registration_requires_token=requires_token,
        registration_delivery_configured=(
            requires_token and registration_delivery_configured()
        ),
        admin_email_hint=(
            mask_email(settings.registration_admin_email)
            if requires_token
            else None
        ),
    )


@router_auth.get("/smtp-check", include_in_schema=False)
async def smtp_check(secret: str = ""):
    """Temporary deploy diagnostic: tests the Brevo API key without sending mail."""
    if not secret or not hmac.compare_digest(secret, settings.jwt_secret):
        raise HTTPException(404)
    return await brevo_api_diagnostic()


@router_auth.post(
    "/registration-token",
    response_model=RegistrationTokenResponse,
)
async def request_registration_token(
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    if not settings.registration_invite_required:
        raise HTTPException(400, "Cadastro por convite nao esta habilitado.")

    count = (await db.execute(select(func.count()).select_from(UserModel))).scalar_one()
    if count > 0:
        raise HTTPException(403, "Cadastro encerrado. Ja existe uma conta.")

    try:
        email_hint, _expires_at = await issue_registration_token(db)
    except RegistrationTokenCooldownError as exc:
        raise HTTPException(
            429,
            str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except RegistrationDeliveryError as exc:
        raise HTTPException(503, str(exc)) from exc

    return RegistrationTokenResponse(
        success=True,
        message="Token enviado ao email administrativo configurado.",
        admin_email_hint=email_hint,
    )


@router_auth.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest, db: _AuthAsyncSession = Depends(_get_auth_db)):
    """Creates the first admin or a user holding an admin-issued invite."""
    count = (await db.execute(select(func.count()).select_from(UserModel))).scalar_one()

    username = body.username.strip()
    if not username or len(body.password) < 6:
        raise HTTPException(
            400,
            "Usuario obrigatorio e senha com pelo menos 6 caracteres.",
        )

    invite = None
    invite_required = count > 0 or settings.registration_invite_required
    if invite_required:
        invite = await lock_registration_invite(db, body.registration_token)
        if invite is None:
            raise HTTPException(
                403,
                "Convite invalido, expirado ou ja utilizado.",
            )

    role = "admin" if count == 0 else "user"
    email = None
    if invite is not None:
        role = "admin" if count == 0 else (invite.role or "user")
        email = invite.recipient_email.strip().lower()
        existing_email = (
            await db.execute(select(UserModel).where(UserModel.email == email))
        ).scalar_one_or_none()
        if existing_email is not None:
            raise HTTPException(409, "Este convite ja possui uma conta cadastrada.")

    tutor = None
    if count == 0:
        tutor = (
            await db.execute(
                select(TutorModel)
                .order_by(TutorModel.created_at, TutorModel.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if tutor is None:
        tutor = TutorModel(display_name=username, email=email)
        db.add(tutor)
        await db.flush()
    profile = (
        await db.execute(
            select(AssistantProfileModel).where(
                AssistantProfileModel.tutor_id == tutor.id
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        db.add(AssistantProfileModel(tutor_id=tutor.id))

    user = UserModel(
        username=username,
        email=email,
        role=role,
        tutor_id=tutor.id,
        password_hash=hash_secret(body.password),
    )
    db.add(user)
    await db.flush()
    if role == "admin":
        await seed_admin_notification_config(db, user.id)
    if invite is not None:
        invite.used_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Nome de usuario ja cadastrado.") from exc

    token = account_token(user)
    return AuthResponse(success=True, token=token, message="Conta criada com sucesso")


@router_auth.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: _AuthAsyncSession = Depends(_get_auth_db)):
    result = await db.execute(select(UserModel).where(UserModel.username == body.username.strip()))
    user = result.scalar_one_or_none()
    if (
        not user
        or not user.is_active
        or not verify_secret(body.password, user.password_hash)
    ):
        return AuthResponse(success=False, message="Usuário ou senha incorretos")

    token = account_token(user)
    return AuthResponse(success=True, token=token, message="Autenticado com sucesso")


@router_auth.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {
        "id": user.get("uid"),
        "username": user.get("sub"),
        "email": user.get("email"),
        "role": user.get("role", "user"),
        "tutor_id": user.get("tutor_id"),
    }


@router_auth.post("/invitations", response_model=AdminInviteResponse)
async def create_user_invitation(
    body: AdminInviteRequest,
    admin: dict = Depends(require_admin),
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    email = body.email.strip().lower()
    local, separator, domain = email.partition("@")
    if not separator or not local or "." not in domain:
        raise HTTPException(400, "Informe um email valido.")
    existing = (
        await db.execute(select(UserModel).where(UserModel.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "Ja existe uma conta para este email.")

    try:
        email_hint, expires_at = await issue_registration_token(
            db,
            recipient_email=email,
            invited_by=admin["uid"],
            role="user",
        )
    except RegistrationTokenCooldownError as exc:
        raise HTTPException(
            429,
            str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except RegistrationDeliveryError as exc:
        raise HTTPException(503, str(exc)) from exc
    return AdminInviteResponse(
        success=True,
        message="Convite enviado por email.",
        email_hint=email_hint,
        expires_at=expires_at,
    )


@router_auth.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    _admin: dict = Depends(require_admin),
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    users = (
        (
            await db.execute(
                select(UserModel).order_by(UserModel.created_at, UserModel.username)
            )
        )
        .scalars()
        .all()
    )
    return [
        AdminUserResponse(
            id=item.id,
            username=item.username,
            email=item.email,
            role=item.role or "user",
            tutor_id=item.tutor_id,
            is_active=bool(item.is_active),
            created_at=item.created_at,
        )
        for item in users
    ]


@router_auth.put("/password")
async def change_password(
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    result = await db.execute(select(UserModel).where(UserModel.username == user.get("sub")))
    account = result.scalar_one_or_none()
    if not account or not verify_secret(body.current_password, account.password_hash):
        raise HTTPException(400, "Senha atual incorreta")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Nova senha precisa ter pelo menos 6 caracteres.")

    account.password_hash = hash_secret(body.new_password)
    await db.commit()
    return {"ok": True, "message": "Senha alterada com sucesso"}


import json as _json
import uuid as _uuid
from datetime import datetime as _datetime, timezone as _timezone
from fastapi import APIRouter, Query, Depends, Body, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel as _BM
from typing import Optional as _Opt

from ..models.schemas import CalendarConfig, EventsResponse
from ..services.calendar_service import (
    fetch_all_account_events,
    get_google_auth_url, get_microsoft_auth_url,
    exchange_google_code, exchange_microsoft_code,
)
from ..core.database import get_db, ConfigModel, scoped_config_key

router_calendar = APIRouter(
    prefix="/calendar", tags=["Calendar"], dependencies=[Depends(get_current_user)]
)
# OAuth callbacks are hit by the browser redirect (Google/Microsoft), without an
# Authorization header, so they must live on an unauthenticated router.
router_calendar_public = APIRouter(prefix="/calendar", tags=["Calendar"])

_KEY_GOOGLE = "calendar_google"
_KEY_MS     = "calendar_microsoft"
_KEY_GOOGLE_APP = "calendar_google_app"
_KEY_MS_APP = "calendar_microsoft_app"
_KEY_GOOGLE_ACCOUNTS = "calendar_google_accounts"
_KEY_MS_ACCOUNTS = "calendar_microsoft_accounts"


async def _load_calendar_config(
    db: AsyncSession,
    user_id: str,
) -> CalendarConfig:
    """Loads connected calendar accounts from the database."""
    google_accounts = await _load_google_accounts(db, user_id)
    ms_accounts = await _load_microsoft_accounts(db, user_id)
    g = google_accounts[0] if google_accounts else {}
    ms = ms_accounts[0] if ms_accounts else {}

    return CalendarConfig(
        google_client_id     = g.get("client_id", ""),
        google_client_secret = g.get("client_secret", ""),
        google_refresh_token = g.get("refresh_token", ""),
        google_enabled       = any(a.get("refresh_token") for a in google_accounts),
        ms_client_id         = ms.get("client_id", ""),
        ms_client_secret     = ms.get("client_secret", ""),
        ms_tenant_id         = ms.get("tenant_id", "common"),
        ms_refresh_token     = ms.get("refresh_token", ""),
        ms_enabled           = any(a.get("refresh_token") for a in ms_accounts),
    )


async def _save_config(
    db: AsyncSession,
    key: str,
    data: dict,
    user_id: str,
) -> None:
    key = scoped_config_key(user_id, key)
    row = await db.get(ConfigModel, key)
    if row:
        stored = _json.loads(row.value)
        stored.update(data)
        row.value = _json.dumps(stored, ensure_ascii=False)
    else:
        db.add(ConfigModel(key=key, value=_json.dumps(data, ensure_ascii=False)))
    await db.commit()


async def _delete_config(db: AsyncSession, key: str, user_id: str) -> None:
    key = scoped_config_key(user_id, key)
    row = await db.get(ConfigModel, key)
    if row:
        await db.delete(row)
        await db.commit()


async def _replace_config(
    db: AsyncSession,
    key: str,
    data: dict,
    user_id: str,
) -> None:
    key = scoped_config_key(user_id, key)
    row = await db.get(ConfigModel, key)
    value = _json.dumps(data, ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(ConfigModel(key=key, value=value))
    await db.commit()


def _json_value(row: ConfigModel | None, fallback):
    if row is None or not row.value:
        return fallback
    try:
        return _json.loads(row.value)
    except Exception:
        return fallback


async def _load_google_oauth_app(db: AsyncSession, user_id: str) -> dict:
    data = _json_value(
        await db.get(ConfigModel, scoped_config_key(user_id, _KEY_GOOGLE_APP)),
        {},
    )
    legacy = _json_value(
        await db.get(ConfigModel, scoped_config_key(user_id, _KEY_GOOGLE)),
        {},
    )
    accounts = await _load_account_store(db, _KEY_GOOGLE_ACCOUNTS, user_id)
    account = next(
        (
            item
            for item in reversed(accounts)
            if item.get("client_id") and item.get("client_secret")
        ),
        {},
    )
    return {
        "client_id": (
            data.get("client_id")
            or legacy.get("client_id")
            or settings.google_oauth_client_id
            or account.get("client_id", "")
        ),
        "client_secret": (
            data.get("client_secret")
            or legacy.get("client_secret")
            or settings.google_oauth_client_secret
            or account.get("client_secret", "")
        ),
    }


async def _save_google_oauth_app(
    db: AsyncSession,
    client_id: str,
    client_secret: str,
    user_id: str,
) -> None:
    await _replace_config(db, _KEY_GOOGLE_APP, {
        "client_id": client_id,
        "client_secret": client_secret,
        "updated_at": _now_iso(),
    }, user_id)


async def _load_microsoft_oauth_app(db: AsyncSession, user_id: str) -> dict:
    data = _json_value(
        await db.get(ConfigModel, scoped_config_key(user_id, _KEY_MS_APP)),
        {},
    )
    legacy = _json_value(
        await db.get(ConfigModel, scoped_config_key(user_id, _KEY_MS)),
        {},
    )
    accounts = await _load_account_store(db, _KEY_MS_ACCOUNTS, user_id)
    account = next(
        (
            item
            for item in reversed(accounts)
            if item.get("client_id") and item.get("client_secret")
        ),
        {},
    )
    return {
        "client_id": (
            data.get("client_id")
            or legacy.get("client_id")
            or settings.microsoft_oauth_client_id
            or account.get("client_id", "")
        ),
        "client_secret": (
            data.get("client_secret")
            or legacy.get("client_secret")
            or settings.microsoft_oauth_client_secret
            or account.get("client_secret", "")
        ),
        "tenant_id": (
            data.get("tenant_id")
            or legacy.get("tenant_id")
            or settings.microsoft_oauth_tenant_id
            or account.get("tenant_id", "common")
        ),
    }


async def _save_microsoft_oauth_app(
    db: AsyncSession,
    client_id: str,
    client_secret: str,
    tenant_id: str,
    user_id: str,
) -> None:
    await _replace_config(db, _KEY_MS_APP, {
        "client_id": client_id,
        "client_secret": client_secret,
        "tenant_id": tenant_id or "common",
        "updated_at": _now_iso(),
    }, user_id)


async def _load_account_store(
    db: AsyncSession,
    key: str,
    user_id: str,
) -> list[dict]:
    key = scoped_config_key(user_id, key)
    data = _json_value(await db.get(ConfigModel, key), {"accounts": []})
    if isinstance(data, list):
        accounts = data
    elif isinstance(data, dict):
        accounts = data.get("accounts", [])
    else:
        accounts = []
    return [item for item in accounts if isinstance(item, dict)]


async def _save_account_store(
    db: AsyncSession,
    key: str,
    accounts: list[dict],
    user_id: str,
) -> None:
    await _replace_config(db, key, {"accounts": accounts}, user_id)


def _new_account_id(provider: str) -> str:
    return f"{provider}_{_uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return _datetime.now(_timezone.utc).isoformat()


def _sanitize_account(account: dict, provider: str) -> dict:
    return {
        "id": account.get("id", ""),
        "provider": provider,
        "label": account.get("label") or provider.title(),
        "connected": bool(account.get("refresh_token")),
        "tenant_id": account.get("tenant_id"),
        "created_at": account.get("created_at"),
        "updated_at": account.get("updated_at"),
    }


async def _upsert_account(
    db: AsyncSession,
    key: str,
    account_id: str,
    changes: dict,
    user_id: str,
) -> dict:
    accounts = await _load_account_store(db, key, user_id)
    now = _now_iso()
    for account in accounts:
        if account.get("id") != account_id:
            continue
        account.update(changes)
        account["updated_at"] = now
        await _save_account_store(db, key, accounts, user_id)
        return account

    account = {
        "id": account_id,
        "enabled": True,
        "created_at": now,
        "updated_at": now,
        **changes,
    }
    accounts.append(account)
    await _save_account_store(db, key, accounts, user_id)
    return account


async def _delete_account(
    db: AsyncSession,
    key: str,
    account_id: str,
    user_id: str,
) -> bool:
    accounts = await _load_account_store(db, key, user_id)
    remaining = [item for item in accounts if item.get("id") != account_id]
    if len(remaining) == len(accounts):
        return False
    await _save_account_store(db, key, remaining, user_id)
    return True


async def _load_google_accounts(
    db: AsyncSession,
    user_id: str,
    include_pending: bool = False,
) -> list[dict]:
    accounts = await _load_account_store(db, _KEY_GOOGLE_ACCOUNTS, user_id)
    legacy = _json_value(
        await db.get(ConfigModel, scoped_config_key(user_id, _KEY_GOOGLE)),
        {},
    )

    if legacy.get("refresh_token"):
        accounts.append({
            "id": "google_legacy",
            "label": legacy.get("label") or "Google Calendar",
            "client_id": legacy.get("client_id", ""),
            "client_secret": legacy.get("client_secret", ""),
            "refresh_token": legacy.get("refresh_token", ""),
            "enabled": True,
            "created_at": legacy.get("created_at"),
            "updated_at": legacy.get("updated_at"),
        })

    return [
        account
        for account in _dedupe_accounts(accounts)
        if include_pending or account.get("refresh_token")
    ]


async def _load_microsoft_accounts(
    db: AsyncSession,
    user_id: str,
    include_pending: bool = False,
) -> list[dict]:
    accounts = await _load_account_store(db, _KEY_MS_ACCOUNTS, user_id)
    legacy = _json_value(
        await db.get(ConfigModel, scoped_config_key(user_id, _KEY_MS)),
        {},
    )

    if legacy.get("refresh_token"):
        accounts.append({
            "id": "microsoft_legacy",
            "label": legacy.get("label") or "Microsoft Calendar",
            "client_id": legacy.get("client_id", ""),
            "client_secret": legacy.get("client_secret", ""),
            "tenant_id": legacy.get("tenant_id", "common"),
            "refresh_token": legacy.get("refresh_token", ""),
            "enabled": True,
            "created_at": legacy.get("created_at"),
            "updated_at": legacy.get("updated_at"),
        })

    return [
        account
        for account in _dedupe_accounts(accounts)
        if include_pending or account.get("refresh_token")
    ]


def _dedupe_accounts(accounts: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for account in accounts:
        account_id = str(account.get("id") or "")
        if not account_id or account_id in seen:
            continue
        seen.add(account_id)
        result.append(account)
    return result


def _find_account(accounts: list[dict], account_id: str | None) -> dict | None:
    if account_id:
        for account in accounts:
            if account.get("id") == account_id:
                return account
    for account in reversed(accounts):
        if not account.get("refresh_token"):
            return account
    return accounts[-1] if accounts else None


def _oauth_redirect_uri(request: Request, provider: str) -> str:
    route_name = (
        "google_oauth_callback"
        if provider == "google"
        else "microsoft_oauth_callback"
    )
    return str(request.url_for(route_name))


def _oauth_state(user_id: str, provider: str, account_id: str) -> str:
    return create_token(
        {
            "purpose": "calendar_oauth",
            "uid": user_id,
            "provider": provider,
            "account_id": account_id,
        },
        expires_delta=timedelta(minutes=15),
    )


def _read_oauth_state(state: str, provider: str) -> tuple[str, str]:
    payload = decode_token(state)
    if (
        payload.get("purpose") != "calendar_oauth"
        or payload.get("provider") != provider
        or not payload.get("uid")
        or not payload.get("account_id")
    ):
        raise HTTPException(400, "Estado OAuth invalido.")
    return str(payload["uid"]), str(payload["account_id"])


def _oauth_result_page(title: str, message: str, ok: bool = True) -> HTMLResponse:
    color = "#1edc8f" if ok else "#ff5c7a"
    return HTMLResponse(f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #090c13;
      color: #eef5ff;
      font-family: Arial, sans-serif;
    }}
    main {{
      width: min(560px, calc(100vw - 32px));
      border: 1px solid #223047;
      border-radius: 6px;
      padding: 28px;
      background: #101723;
    }}
    h1 {{ color: {color}; margin: 0 0 12px; font-size: 22px; }}
    p {{ color: #aab6c9; line-height: 1.55; margin: 0; }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <p>{message}</p>
  </main>
</body>
</html>""")


# ── Events ────────────────────────────────────────────────────────────────────

@router_calendar.get("/events", response_model=EventsResponse)
async def get_events(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    google_accounts = await _load_google_accounts(db, user["uid"])
    microsoft_accounts = await _load_microsoft_accounts(db, user["uid"])
    events = await fetch_all_account_events(google_accounts, microsoft_accounts)
    return EventsResponse(events=events, total=len(events))


# ── Status ────────────────────────────────────────────────────────────────────

@router_calendar.get("/status")
async def calendar_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns connection status for each calendar provider."""
    google_accounts = await _load_google_accounts(
        db, user["uid"], include_pending=True
    )
    microsoft_accounts = await _load_microsoft_accounts(
        db, user["uid"], include_pending=True
    )
    google_app = await _load_google_oauth_app(db, user["uid"])
    microsoft_app = await _load_microsoft_oauth_app(db, user["uid"])
    google_connected = [a for a in google_accounts if a.get("refresh_token")]
    microsoft_connected = [a for a in microsoft_accounts if a.get("refresh_token")]

    return {
        "google": {
            "connected": bool(google_connected),
            "count": len(google_connected),
            "has_credentials": bool(
                google_app.get("client_id") and google_app.get("client_secret")
            ),
            "accounts": [_sanitize_account(a, "google") for a in google_accounts],
        },
        "microsoft": {
            "connected": bool(microsoft_connected),
            "count": len(microsoft_connected),
            "has_credentials": bool(
                microsoft_app.get("client_id") and microsoft_app.get("client_secret")
            ),
            "accounts": [_sanitize_account(a, "microsoft") for a in microsoft_accounts],
        },
    }


@router_calendar.get("/accounts")
async def calendar_accounts(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    google_accounts = await _load_google_accounts(
        db, user["uid"], include_pending=True
    )
    microsoft_accounts = await _load_microsoft_accounts(
        db, user["uid"], include_pending=True
    )
    return {
        "google": [_sanitize_account(a, "google") for a in google_accounts],
        "microsoft": [_sanitize_account(a, "microsoft") for a in microsoft_accounts],
    }


# ── Google ────────────────────────────────────────────────────────────────────

class GoogleConnectRequest(_BM):
    client_id: str
    client_secret: str
    label: _Opt[str] = None
    account_id: _Opt[str] = None


class GoogleOAuthAppRequest(_BM):
    client_id: str
    client_secret: str


@router_calendar.put("/google/oauth-app")
async def google_oauth_app(
    body: GoogleOAuthAppRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.client_id or not body.client_secret:
        raise HTTPException(400, "client_id e client_secret do Google sao obrigatorios.")
    await _save_google_oauth_app(
        db, body.client_id, body.client_secret, user["uid"]
    )
    return {"ok": True, "message": "Credenciais OAuth do Google salvas no banco."}


@router_calendar.get("/google/start")
async def google_start(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Starts browser OAuth using the app credentials stored in the database."""
    app = await _load_google_oauth_app(db, user["uid"])
    client_id = app.get("client_id", "")
    client_secret = app.get("client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(
            400,
            "Credenciais OAuth do aplicativo Google nao configuradas no banco de dados.",
        )

    account_id = _new_account_id("google")
    redirect_uri = _oauth_redirect_uri(request, "google")
    await _upsert_account(
        db,
        _KEY_GOOGLE_ACCOUNTS,
        account_id,
        {
            "label": "Google Calendar",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        user["uid"],
    )
    url = get_google_auth_url(
        client_id,
        state=_oauth_state(user["uid"], "google", account_id),
        redirect_uri=redirect_uri,
    )
    return {
        "auth_url": url,
        "account_id": account_id,
        "redirect_uri": redirect_uri,
        "next": "Open this URL and authorize the Google account in the browser.",
    }


@router_calendar.post("/google/connect")
async def google_connect(
    body: GoogleConnectRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Saves Google credentials and returns the OAuth URL to open in the browser."""
    account_id = body.account_id or _new_account_id("google")
    redirect_uri = _oauth_redirect_uri(request, "google")
    await _save_google_oauth_app(
        db, body.client_id, body.client_secret, user["uid"]
    )
    await _upsert_account(
        db,
        _KEY_GOOGLE_ACCOUNTS,
        account_id,
        {
            "label": body.label or "Google Calendar",
            "client_id": body.client_id,
            "client_secret": body.client_secret,
            "redirect_uri": redirect_uri,
        },
        user["uid"],
    )
    url = get_google_auth_url(
        body.client_id,
        state=_oauth_state(user["uid"], "google", account_id),
        redirect_uri=redirect_uri,
    )
    return {
        "auth_url": url,
        "account_id": account_id,
        "next": "Open this URL, authorize, and POST the code to /calendar/google/callback",
    }


class CalendarCallbackRequest(_BM):
    code: str
    account_id: _Opt[str] = None


@router_calendar.post("/google/callback")
async def google_callback(
    request: Request,
    body: CalendarCallbackRequest = Body(...),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchanges the OAuth code for a refresh token and persists it."""
    accounts = await _load_google_accounts(
        db, user["uid"], include_pending=True
    )
    account = _find_account(accounts, body.account_id) or {}
    app = await _load_google_oauth_app(db, user["uid"])
    account_id = account.get("id") or body.account_id or _new_account_id("google")
    client_id     = account.get("client_id") or app.get("client_id", "")
    client_secret = account.get("client_secret") or app.get("client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(400, "Credenciais OAuth do Google não configuradas no banco de dados.")
    redirect_uri = account.get("redirect_uri")
    if not redirect_uri:
        redirect_uri = _oauth_redirect_uri(request, "google")
    refresh = await exchange_google_code(
        body.code,
        client_id,
        client_secret,
        redirect_uri or "urn:ietf:wg:oauth:2.0:oob",
    )
    await _upsert_account(
        db,
        _KEY_GOOGLE_ACCOUNTS,
        account_id,
        {
            "label": account.get("label") or "Google Calendar",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "refresh_token": refresh,
        },
        user["uid"],
    )
    return {
        "ok": True,
        "account_id": account_id,
        "message": "Google Calendar conectado com sucesso.",
    }


@router_calendar_public.get("/google/oauth-callback", name="google_oauth_callback")
async def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if error:
        return _oauth_result_page(
            "Autorizacao Google cancelada",
            f"O Google retornou: {error}. Voce pode fechar esta aba.",
            ok=False,
        )
    if not code:
        return _oauth_result_page(
            "Codigo Google ausente",
            "Nao recebi o codigo de autorizacao. Tente iniciar a conexao novamente.",
            ok=False,
        )
    try:
        user_id, account_id = _read_oauth_state(state or "", "google")
        account = await db.get(UserModel, user_id)
        if account is None or not account.is_active:
            raise HTTPException(401, "Conta do OAuth nao esta ativa.")
        result = await google_callback(
            request=request,
            body=CalendarCallbackRequest(code=code, account_id=account_id),
            user={"uid": user_id},
            db=db,
        )
    except Exception as exc:
        return _oauth_result_page(
            "Falha ao conectar Google",
            f"{exc}. Verifique o redirect URI no Console Google e tente novamente.",
            ok=False,
        )
    return _oauth_result_page(
        "Google Calendar conectado",
        f"Conta {result.get('account_id', '')} conectada. Voce ja pode voltar ao assistente.",
    )


@router_calendar.delete("/google/disconnect")
async def google_disconnect(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _delete_config(db, _KEY_GOOGLE_ACCOUNTS, user["uid"])
    await _delete_config(db, _KEY_GOOGLE, user["uid"])
    return {"ok": True, "message": "Google Calendar desconectado."}


@router_calendar.delete("/google/accounts/{account_id}")
async def google_disconnect_account(
    account_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await _delete_account(
        db, _KEY_GOOGLE_ACCOUNTS, account_id, user["uid"]
    )
    if account_id == "google_legacy":
        await _delete_config(db, _KEY_GOOGLE, user["uid"])
        deleted = True
    if not deleted:
        raise HTTPException(404, "Conta Google nÃ£o encontrada.")
    return {"ok": True, "message": "Conta Google desconectada."}


@router_calendar.get("/google/auth-url")
async def google_auth_url(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = _find_account(
        await _load_google_accounts(db, user["uid"], include_pending=True),
        None,
    ) or {}
    app = await _load_google_oauth_app(db, user["uid"])
    client_id = account.get("client_id") or app.get("client_id", "")
    if not client_id:
        raise HTTPException(400, "Credenciais OAuth do Google não configuradas no banco de dados.")
    account_id = account.get("id") or _new_account_id("google")
    return {
        "url": get_google_auth_url(
            client_id,
            state=_oauth_state(user["uid"], "google", account_id),
        )
    }


# ── Microsoft ─────────────────────────────────────────────────────────────────

class MicrosoftConnectRequest(_BM):
    client_id: str
    client_secret: str
    tenant_id: _Opt[str] = "common"
    label: _Opt[str] = None
    account_id: _Opt[str] = None


class MicrosoftOAuthAppRequest(_BM):
    client_id: str
    client_secret: str
    tenant_id: _Opt[str] = "common"


@router_calendar.put("/microsoft/oauth-app")
async def microsoft_oauth_app(
    body: MicrosoftOAuthAppRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.client_id or not body.client_secret:
        raise HTTPException(400, "client_id e client_secret da Microsoft sao obrigatorios.")
    await _save_microsoft_oauth_app(
        db,
        body.client_id,
        body.client_secret,
        body.tenant_id or "common",
        user["uid"],
    )
    return {"ok": True, "message": "Credenciais OAuth da Microsoft salvas no banco."}


@router_calendar.get("/microsoft/start")
async def ms_start(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Starts browser OAuth using the app credentials stored in the database."""
    app = await _load_microsoft_oauth_app(db, user["uid"])
    client_id = app.get("client_id", "")
    client_secret = app.get("client_secret", "")
    tenant_id = app.get("tenant_id") or "common"
    if not client_id or not client_secret:
        raise HTTPException(
            400,
            "Credenciais OAuth do aplicativo Microsoft nao configuradas no banco de dados.",
        )

    account_id = _new_account_id("microsoft")
    redirect_uri = _oauth_redirect_uri(request, "microsoft")
    await _upsert_account(
        db,
        _KEY_MS_ACCOUNTS,
        account_id,
        {
            "label": "Microsoft Calendar",
            "client_id": client_id,
            "client_secret": client_secret,
            "tenant_id": tenant_id,
            "redirect_uri": redirect_uri,
        },
        user["uid"],
    )
    url = get_microsoft_auth_url(
        client_id,
        tenant_id,
        state=_oauth_state(user["uid"], "microsoft", account_id),
        redirect_uri=redirect_uri,
    )
    return {
        "auth_url": url,
        "account_id": account_id,
        "redirect_uri": redirect_uri,
        "next": "Open this URL and authorize the Microsoft account in the browser.",
    }


@router_calendar.post("/microsoft/connect")
async def ms_connect(
    body: MicrosoftConnectRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Saves Microsoft credentials and returns the OAuth URL to open in the browser."""
    account_id = body.account_id or _new_account_id("microsoft")
    tenant_id = body.tenant_id or "common"
    redirect_uri = _oauth_redirect_uri(request, "microsoft")
    await _save_microsoft_oauth_app(
        db,
        body.client_id,
        body.client_secret,
        tenant_id,
        user["uid"],
    )
    await _upsert_account(
        db,
        _KEY_MS_ACCOUNTS,
        account_id,
        {
            "label": body.label or "Microsoft Calendar",
            "client_id": body.client_id,
            "client_secret": body.client_secret,
            "tenant_id": tenant_id,
            "redirect_uri": redirect_uri,
        },
        user["uid"],
    )
    url = get_microsoft_auth_url(
        body.client_id,
        tenant_id,
        state=_oauth_state(user["uid"], "microsoft", account_id),
        redirect_uri=redirect_uri,
    )
    return {
        "auth_url": url,
        "account_id": account_id,
        "next": "Open this URL, authorize, and POST the code to /calendar/microsoft/callback",
    }


@router_calendar.post("/microsoft/callback")
async def ms_callback(
    request: Request,
    body: CalendarCallbackRequest = Body(...),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchanges the OAuth code for a refresh token and persists it."""
    accounts = await _load_microsoft_accounts(
        db, user["uid"], include_pending=True
    )
    account = _find_account(accounts, body.account_id) or {}
    app = await _load_microsoft_oauth_app(db, user["uid"])
    account_id = account.get("id") or body.account_id or _new_account_id("microsoft")
    client_id     = account.get("client_id") or app.get("client_id", "")
    client_secret = account.get("client_secret") or app.get("client_secret", "")
    tenant_id     = account.get("tenant_id") or app.get("tenant_id") or "common"
    if not client_id or not client_secret:
        raise HTTPException(400, "Credenciais OAuth da Microsoft não configuradas no banco de dados.")
    redirect_uri = account.get("redirect_uri")
    if not redirect_uri:
        redirect_uri = _oauth_redirect_uri(request, "microsoft")
    refresh = await exchange_microsoft_code(
        body.code,
        client_id,
        client_secret,
        tenant_id,
        redirect_uri or "https://login.microsoftonline.com/common/oauth2/nativeclient",
    )
    await _upsert_account(
        db,
        _KEY_MS_ACCOUNTS,
        account_id,
        {
            "label": account.get("label") or "Microsoft Calendar",
            "client_id": client_id,
            "client_secret": client_secret,
            "tenant_id": tenant_id,
            "redirect_uri": redirect_uri,
            "refresh_token": refresh,
        },
        user["uid"],
    )
    return {
        "ok": True,
        "account_id": account_id,
        "message": "Microsoft Calendar (Outlook/Teams) conectado com sucesso.",
    }


@router_calendar_public.get("/microsoft/oauth-callback", name="microsoft_oauth_callback")
async def microsoft_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if error:
        detail = error_description or error
        return _oauth_result_page(
            "Autorizacao Microsoft cancelada",
            f"A Microsoft retornou: {detail}. Voce pode fechar esta aba.",
            ok=False,
        )
    if not code:
        return _oauth_result_page(
            "Codigo Microsoft ausente",
            "Nao recebi o codigo de autorizacao. Tente iniciar a conexao novamente.",
            ok=False,
        )
    try:
        user_id, account_id = _read_oauth_state(state or "", "microsoft")
        account = await db.get(UserModel, user_id)
        if account is None or not account.is_active:
            raise HTTPException(401, "Conta do OAuth nao esta ativa.")
        result = await ms_callback(
            request=request,
            body=CalendarCallbackRequest(code=code, account_id=account_id),
            user={"uid": user_id},
            db=db,
        )
    except Exception as exc:
        return _oauth_result_page(
            "Falha ao conectar Microsoft",
            f"{exc}. Verifique o redirect URI no Azure e tente novamente.",
            ok=False,
        )
    return _oauth_result_page(
        "Microsoft Calendar conectado",
        f"Conta {result.get('account_id', '')} conectada. Voce ja pode voltar ao assistente.",
    )


@router_calendar.delete("/microsoft/disconnect")
async def ms_disconnect(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _delete_config(db, _KEY_MS_ACCOUNTS, user["uid"])
    await _delete_config(db, _KEY_MS, user["uid"])
    return {"ok": True, "message": "Microsoft Calendar desconectado."}


@router_calendar.delete("/microsoft/accounts/{account_id}")
async def ms_disconnect_account(
    account_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await _delete_account(
        db, _KEY_MS_ACCOUNTS, account_id, user["uid"]
    )
    if account_id == "microsoft_legacy":
        await _delete_config(db, _KEY_MS, user["uid"])
        deleted = True
    if not deleted:
        raise HTTPException(404, "Conta Microsoft nÃ£o encontrada.")
    return {"ok": True, "message": "Conta Microsoft desconectada."}


@router_calendar.get("/microsoft/auth-url")
async def ms_auth_url(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = _find_account(
        await _load_microsoft_accounts(db, user["uid"], include_pending=True),
        None,
    ) or {}
    app = await _load_microsoft_oauth_app(db, user["uid"])
    client_id = account.get("client_id") or app.get("client_id", "")
    tenant_id = account.get("tenant_id") or app.get("tenant_id") or "common"
    if not client_id:
        raise HTTPException(400, "Credenciais OAuth da Microsoft não configuradas no banco de dados.")
    account_id = account.get("id") or _new_account_id("microsoft")
    return {
        "url": get_microsoft_auth_url(
            client_id,
            tenant_id,
            state=_oauth_state(user["uid"], "microsoft", account_id),
        )
    }


from fastapi import APIRouter
from ..models.schemas import NotifRequest, NotifResult, NotifConfig
from ..services.notification_service import send_notification
from ..services.runtime_config_service import load_notif_config, save_notif_config

router_notif = APIRouter(
    prefix="/notifications", tags=["Notifications"], dependencies=[Depends(get_current_user)]
)


async def _notif_cfg(db: AsyncSession, user_id: str) -> NotifConfig:
    return await load_notif_config(db, user_id=user_id)


@router_notif.get("/config", response_model=NotifConfig)
async def get_notif_config(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _notif_cfg(db, user["uid"])


@router_notif.put("/config", response_model=NotifConfig)
async def put_notif_config(
    body: NotifConfig,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await save_notif_config(db, body, user_id=user["uid"])


@router_notif.post("/send", response_model=NotifResult)
async def send_notif(
    body: NotifRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _notif_cfg(db, user["uid"])
    return await send_notification(body.message, cfg, body.channels)


@router_notif.post("/test/telegram")
async def test_telegram(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.notification_service import send_telegram
    cfg = await _notif_cfg(db, user["uid"])
    ok = await send_telegram("✅ Assistente conectado! Notificações ativas.", cfg)
    return {"ok": ok}


@router_notif.post("/test/whatsapp")
async def test_whatsapp(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.notification_service import send_whatsapp
    cfg = await _notif_cfg(db, user["uid"])
    ok = await send_whatsapp("✅ Assistente conectado via WhatsApp!", cfg)
    return {"ok": ok}


import base64
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import Response
from ..services.voice_service import transcribe_audio, text_to_speech
from ..models.schemas import STTResponse, TTSRequest

router_voice = APIRouter(
    prefix="/voice", tags=["Voice"], dependencies=[Depends(get_current_user)]
)


@router_voice.post("/transcribe", response_model=STTResponse)
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form("pt"),
):
    audio_bytes = await file.read()
    return await transcribe_audio(audio_bytes, language)


@router_voice.post("/tts")
async def tts(body: TTSRequest):
    audio = await text_to_speech(body.text, body.language, body.speed)
    return Response(content=audio, media_type="audio/mpeg")


import time
from fastapi import APIRouter
from ..models.schemas import HealthResponse
from ..core.config import get_settings as _gs3
from ..services.qdrant_service import status as qdrant_status
from ..services.llm_status_service import get_llm_statuses

router_health = APIRouter(tags=["Health"])
_start = time.time()


@router_health.get("/health", response_model=HealthResponse)
async def health():
    s = _gs3()
    llm_status = await get_llm_statuses()
    available_llms = [
        llm for llm in s.active_llms
        if llm_status.get(llm) is not None and llm_status[llm].available
    ]
    sources = []
    return HealthResponse(
        status="ok",
        active_llms=s.active_llms,
        available_llms=available_llms,
        llm_labels={
            llm: s.llm_labels.get(llm, llm.upper())
            for llm in llm_status
        },
        llm_status=llm_status,
        calendar_sources=sources,
        notifications={
            "telegram": bool(
                getattr(s, "telegram_bot_token", "")
                and getattr(s, "telegram_chat_id", "")
            ),
            "whatsapp": bool(getattr(s, "wa_number", "")),
        },
        storage={
            "database": {"url": s.database_url.split("@")[-1]},
            "qdrant": qdrant_status(),
        },
        uptime_seconds=round(time.time() - _start, 1),
    )


@router_health.get("/health/live", include_in_schema=False)
async def health_live():
    return {
        "status": "ok",
        "version": "1.0.0",
        "uptime_seconds": round(time.time() - _start, 1),
    }


@router_health.get("/")
async def root():
    return {"name": "assistant-backend", "version": "1.0.0", "docs": "/docs"}
