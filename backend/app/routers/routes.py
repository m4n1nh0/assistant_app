"""Rotas de autenticacao, calendario, notificacao, voz e health.

Sao cinco routers em um arquivo so, na ordem em que aparecem:

| Router | Prefixo | O que cobre |
| --- | --- | --- |
| `router_auth` | `/auth` | login, cadastro por convite, recuperacao de senha, contas |
| `router_calendar` | `/calendar` | contas conectadas, eventos e o fluxo OAuth de cada provedor |
| `router_calendar_public` | `/calendar` | apenas os callbacks de OAuth, que o provedor chama sem token |
| `router_notif` | `/notifications` | preferencias, envio e teste de canal |
| `router_voice` | `/voice` | transcricao e sintese de fala |
| `router_health` | - | `/health`, `/health/live` e a raiz |

Duas regras atravessam o bloco de autenticacao: as rotas publicas tem rate limit
por IP, e as respostas nao revelam se uma conta existe - pedido de recuperacao
responde a mesma coisa para email cadastrado ou nao, senao o endpoint vira um
verificador de quais emails tem conta.
"""

import hmac
from datetime import datetime, timedelta, timezone

import pytz
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func, or_
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
from ..core.config import build_revision, get_settings
from ..core.rate_limit import rate_limit
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
    PasswordRecoveryRequest, PasswordRecoveryConfirmRequest,
    PublicMessageResponse,
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
from ..services.password_recovery_service import (
    consume_password_reset_token,
    issue_password_reset_token,
)
from ..services.user_llm_config_service import runtime_settings, user_llm_context

router_auth = APIRouter(prefix="/auth", tags=["Auth"])
settings = get_settings()

# General per-IP ceiling plus a tighter, shorter-window burst guard, stacked on
# endpoints that are public and prone to abuse (token spam, brute force).
_public_auth_rate_limit = [
    Depends(rate_limit(times=20, seconds=60)),
    Depends(rate_limit(times=5, seconds=10)),
]


@router_auth.get("/status", response_model=AuthStatusResponse)
async def auth_status(db: _AuthAsyncSession = Depends(_get_auth_db)):
    """Diz se ja existe conta, se o cadastro exige convite e como e a entrega.

    E o que a interface consulta na primeira execucao para escolher entre a tela de
    criacao do primeiro administrador e a tela de login.
    """
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
    dependencies=_public_auth_rate_limit,
)
async def request_registration_token(
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    """Emite o token do primeiro cadastro e envia ao email administrativo.

    So funciona enquanto nao existe nenhuma conta e o cadastro por convite esta
    habilitado.
    """
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


@router_auth.post(
    "/register",
    response_model=AuthResponse,
    dependencies=_public_auth_rate_limit,
)
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


@router_auth.post(
    "/login",
    response_model=AuthResponse,
    dependencies=_public_auth_rate_limit,
)
async def login(body: LoginRequest, db: _AuthAsyncSession = Depends(_get_auth_db)):
    """Autentica por usuario ou email e devolve o token de sessao.

    A resposta de credencial errada e a mesma para usuario inexistente, senha errada
    ou conta desativada.
    """
    identifier = body.username.strip()
    result = await db.execute(
        select(UserModel).where(
            or_(
                UserModel.username == identifier,
                func.lower(UserModel.email) == identifier.lower(),
            )
        )
    )
    user = result.scalar_one_or_none()
    if (
        not user
        or not user.is_active
        or not verify_secret(body.password, user.password_hash)
    ):
        return AuthResponse(success=False, message="Usuário ou senha incorretos")

    token = account_token(user)
    return AuthResponse(success=True, token=token, message="Autenticado com sucesso")


@router_auth.post(
    "/password-recovery/request",
    response_model=PublicMessageResponse,
    dependencies=_public_auth_rate_limit,
)
async def request_password_recovery(
    body: PasswordRecoveryRequest,
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    # The public response deliberately does not reveal whether the account,
    # email delivery or cooldown exists.
    """Inicia a recuperacao de senha enviando token ao email da conta.

    A resposta e sempre a mesma exista ou nao a conta - de proposito.
    """
    await issue_password_reset_token(db, body.identifier[:255])
    return PublicMessageResponse(
        message=(
            "Se houver uma conta ativa com email vinculado, enviaremos um "
            "token de recuperacao."
        )
    )


@router_auth.post(
    "/password-recovery/confirm",
    response_model=PublicMessageResponse,
    dependencies=_public_auth_rate_limit,
)
async def confirm_password_recovery(
    body: PasswordRecoveryConfirmRequest,
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    """Troca a senha usando o token recebido por email.

    O token e queimado no uso e as sessoes abertas da conta caem junto.
    """
    if len(body.new_password) < 6:
        raise HTTPException(400, "Nova senha precisa ter pelo menos 6 caracteres.")
    consumed = await consume_password_reset_token(
        db,
        body.token,
        hash_secret(body.new_password),
    )
    if not consumed:
        raise HTTPException(400, "Token invalido, expirado ou ja utilizado.")
    return PublicMessageResponse(message="Senha redefinida com sucesso.")


@router_auth.post("/refresh", response_model=AuthResponse)
async def refresh(
    user: dict = Depends(get_current_user),
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    """Troca um token ainda valido por outro com prazo cheio.

    Sem isso uma aula longa esbarra no fim das 24h do token no meio da
    gravacao e os blocos de audio passam a voltar 401.
    """
    account = await db.get(UserModel, user["uid"])
    if account is None or not account.is_active:
        raise HTTPException(401, "Conta inexistente ou desativada")
    return AuthResponse(
        success=True,
        token=account_token(account),
        message="Sessao renovada",
    )


@router_auth.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Devolve a identidade da conta autenticada."""
    return {
        "id": user.get("uid"),
        "username": user.get("sub"),
        "email": user.get("email"),
        "role": user.get("role", "user"),
        "tutor_id": user.get("tutor_id"),
    }


@router_auth.post(
    "/invitations",
    response_model=AdminInviteResponse,
    dependencies=[Depends(rate_limit(times=30, seconds=60))],
)
async def create_user_invitation(
    body: AdminInviteRequest,
    admin: dict = Depends(require_admin),
    db: _AuthAsyncSession = Depends(_get_auth_db),
):
    """Convida um novo usuario por email. Restrito a administrador."""
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
    """Lista as contas da instalacao. Restrito a administrador."""
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
    """Troca a senha da conta autenticada, exigindo a senha atual."""
    result = await db.execute(select(UserModel).where(UserModel.username == user.get("sub")))
    account = result.scalar_one_or_none()
    if not account or not verify_secret(body.current_password, account.password_hash):
        raise HTTPException(400, "Senha atual incorreta")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Nova senha precisa ter pelo menos 6 caracteres.")

    account.password_hash = hash_secret(body.new_password)
    account.auth_version = int(account.auth_version or 0) + 1
    await db.commit()
    return {"ok": True, "message": "Senha alterada com sucesso"}


import json as _json
import uuid as _uuid
import hashlib as _hashlib
import base64 as _base64
import html as _html
import secrets as _secrets
from datetime import date as _date, datetime as _datetime, timezone as _timezone
from fastapi import APIRouter, Query, Depends, Body, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel as _BM
from typing import Optional as _Opt

from ..models.schemas import (
    CalendarConfig,
    CalendarEvent,
    CalendarEventCreateRequest,
    ClassAgendaCreateRequest,
    ClassAgendaCreateResponse,
    EventsResponse,
)
from ..services.calendar_service import (
    create_google_account_event,
    create_microsoft_account_event,
    fetch_all_account_events,
    get_google_auth_url, get_microsoft_auth_url,
    exchange_google_code, exchange_microsoft_code, fetch_microsoft_profile,
    microsoft_auth_error_message, MicrosoftAuthenticationError,
    validate_microsoft_session,
)
from ..services.credential_storage_service import (
    encrypt_credential,
)
from ..services.microsoft_identity_service import (
    hydrate_microsoft_account,
    microsoft_application_config,
)
from ..core.database import (
    get_db,
    ClassCalendarSeriesModel,
    ClassGroupModel,
    ClassScheduleModel,
    ConfigModel,
    scoped_config_key,
)

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
    # A single multitenant application belongs to the deployment, not to an
    # end user. Keeping these values in environment/secret-manager settings is
    # what lets the UI offer only the official Microsoft login.
    return microsoft_application_config()


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
    stored_status = str(account.get("connection_status") or "")
    connected = bool(account.get("refresh_token")) and stored_status not in {
        "authorization_pending", "reconnect_required"
    }
    return {
        "id": account.get("id", ""),
        "provider": provider,
        "label": account.get("label") or provider.title(),
        "connected": connected,
        "status": stored_status or ("connected" if connected else "pending"),
        "display_name": account.get("display_name"),
        "email": account.get("email"),
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

    result: list[dict] = []
    for stored in _dedupe_accounts(accounts):
        if not include_pending and not stored.get("refresh_token"):
            continue
        result.append(hydrate_microsoft_account(stored))
    return result


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
    safe_title = _html.escape(title)
    safe_message = _html.escape(message)
    return HTMLResponse(f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
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
    <h1>{safe_title}</h1>
    <p>{safe_message}</p>
  </main>
</body>
</html>""")


# ── Events ────────────────────────────────────────────────────────────────────

@router_calendar.get("/events", response_model=EventsResponse)
async def get_events(
    start: datetime | None = None,
    end: datetime | None = None,
    max_results: int = 25,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sem parametros mantem a janela padrao (proximos 7 dias). A visao de
    calendario da interface envia start/end do mes visivel."""
    if start is not None and end is not None:
        if end <= start:
            raise HTTPException(422, "O fim do periodo deve ser apos o inicio.")
        if (end - start).days > 92:
            raise HTTPException(422, "Periodo maximo de 92 dias por consulta.")
    google_accounts = await _load_google_accounts(db, user["uid"])
    microsoft_accounts = await _load_microsoft_accounts(db, user["uid"])
    events = await fetch_all_account_events(
        google_accounts,
        microsoft_accounts,
        start_time=start,
        end_time=end,
        max_results=max(1, min(max_results, 100)),
    )
    return EventsResponse(events=events, total=len(events))


@router_calendar.post("/events", response_model=CalendarEvent, status_code=201)
async def create_event(
    body: CalendarEventCreateRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates an event only after the desktop confirmation dialog."""
    if not body.confirmed:
        raise HTTPException(400, "Confirme o evento antes de cria-lo.")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "O titulo do evento e obrigatorio.")

    try:
        event_timezone = pytz.timezone(body.timezone)
    except pytz.UnknownTimeZoneError as exc:
        raise HTTPException(422, "Fuso horario IANA invalido.") from exc

    start_time = body.start_time
    end_time = body.end_time
    if start_time.tzinfo is None:
        start_time = event_timezone.localize(start_time)
    if end_time.tzinfo is None:
        end_time = event_timezone.localize(end_time)
    if end_time <= start_time:
        raise HTTPException(422, "O termino deve ser posterior ao inicio.")
    if start_time <= _datetime.now(_timezone.utc):
        raise HTTPException(422, "O evento precisa comecar no futuro.")

    if body.provider == "google":
        accounts = await _load_google_accounts(db, user["uid"])
    else:
        accounts = await _load_microsoft_accounts(db, user["uid"])
    account = next(
        (
            item
            for item in accounts
            if item.get("id") == body.account_id and item.get("refresh_token")
        ),
        None,
    )
    if account is None:
        raise HTTPException(404, "Conta de calendario conectada nao encontrada.")

    kwargs = {
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "description": body.description.strip() if body.description else None,
        "location": body.location.strip() if body.location else None,
    }
    try:
        if body.provider == "google":
            return await create_google_account_event(
                account,
                timezone_name=body.timezone,
                **kwargs,
            )
        return await create_microsoft_account_event(account, **kwargs)
    except Exception as exc:
        detail = str(exc)
        if "insufficient" in detail.lower() or "permission" in detail.lower():
            detail += " Reconecte a conta para conceder a permissao de escrita."
        raise HTTPException(502, detail) from exc


def _first_class_occurrence(
    *,
    date_from: _date,
    date_to: _date,
    weekday: int,
    start_value: str,
    end_value: str,
    event_timezone,
) -> tuple[_datetime, _datetime] | None:
    """Resolve a primeira aula futura da serie no intervalo informado."""
    try:
        start_clock = _datetime.strptime(start_value, "%H:%M").time()
        end_clock = (
            _datetime.strptime(end_value, "%H:%M").time()
            if end_value
            else None
        )
    except ValueError as exc:
        raise ValueError("horario deve usar HH:MM") from exc

    occurrence_date = date_from + timedelta(
        days=(weekday - date_from.weekday()) % 7
    )
    while occurrence_date <= date_to:
        start_time = event_timezone.localize(
            _datetime.combine(occurrence_date, start_clock)
        )
        if start_time > _datetime.now(_timezone.utc):
            if end_clock is None:
                end_time = start_time + timedelta(minutes=90)
            else:
                end_time = event_timezone.localize(
                    _datetime.combine(occurrence_date, end_clock)
                )
                if end_time <= start_time:
                    end_time += timedelta(days=1)
            return start_time, end_time
        occurrence_date += timedelta(days=7)
    return None


@router_calendar.post(
    "/class-agenda",
    response_model=ClassAgendaCreateResponse,
    status_code=201,
)
async def create_class_agenda(
    body: ClassAgendaCreateRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cria series semanais das turmas em uma unica operacao confirmada."""
    if not body.confirmed:
        raise HTTPException(400, "Confirme a agenda das turmas antes de cria-la.")
    if body.date_to < body.date_from:
        raise HTTPException(422, "A data final deve ser igual ou posterior a inicial.")
    if (body.date_to - body.date_from).days > 370:
        raise HTTPException(422, "A agenda pode cobrir no maximo 371 dias.")
    try:
        event_timezone = pytz.timezone(body.timezone)
    except pytz.UnknownTimeZoneError as exc:
        raise HTTPException(422, "Fuso horario IANA invalido.") from exc

    tutor_id = user.get("tutor_id")
    if not tutor_id:
        account_user = await db.get(UserModel, user["uid"])
        tutor_id = account_user.tutor_id if account_user else None
    if not tutor_id:
        raise HTTPException(403, "Usuario sem perfil de professor.")

    class_ids = list(dict.fromkeys(body.class_ids))
    groups = (
        (
            await db.execute(
                select(ClassGroupModel).where(
                    ClassGroupModel.tutor_id == tutor_id,
                    ClassGroupModel.id.in_(class_ids),
                    ClassGroupModel.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if len(groups) != len(class_ids):
        raise HTTPException(404, "Uma ou mais turmas ativas nao foram encontradas.")

    if body.provider == "google":
        accounts = await _load_google_accounts(db, user["uid"])
    else:
        accounts = await _load_microsoft_accounts(db, user["uid"])
    account = next(
        (
            item
            for item in accounts
            if item.get("id") == body.account_id and item.get("refresh_token")
        ),
        None,
    )
    if account is None:
        raise HTTPException(404, "Conta de calendario conectada nao encontrada.")

    schedules = (
        (
            await db.execute(
                select(ClassScheduleModel).where(
                    ClassScheduleModel.class_group_id.in_(class_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    group_by_id = {group.id: group for group in groups}
    entries: list[tuple[ClassScheduleModel, str]] = []
    for schedule in schedules:
        fingerprint_source = "|".join(
            [
                user["uid"], body.provider, body.account_id,
                schedule.class_group_id, str(schedule.weekday),
                schedule.start_time, schedule.end_time,
                body.date_to.isoformat(), body.timezone,
            ]
        )
        fingerprint = _hashlib.sha256(fingerprint_source.encode()).hexdigest()
        entries.append((schedule, fingerprint))

    fingerprints = [fingerprint for _, fingerprint in entries]
    existing = set()
    if fingerprints:
        existing = set(
            (
                await db.execute(
                    select(ClassCalendarSeriesModel.fingerprint).where(
                        ClassCalendarSeriesModel.fingerprint.in_(fingerprints)
                    )
                )
            )
            .scalars()
            .all()
        )

    response = ClassAgendaCreateResponse(class_count=len(groups))
    for schedule, fingerprint in entries:
        group = group_by_id[schedule.class_group_id]
        if fingerprint in existing:
            response.skipped_series += 1
            continue
        if not schedule.start_time:
            response.failed_series += 1
            response.errors.append(
                f"{group.code or group.name}: horario inicial nao informado."
            )
            continue
        try:
            occurrence = _first_class_occurrence(
                date_from=body.date_from,
                date_to=body.date_to,
                weekday=schedule.weekday,
                start_value=schedule.start_time,
                end_value=schedule.end_time,
                event_timezone=event_timezone,
            )
        except ValueError as exc:
            response.failed_series += 1
            response.errors.append(f"{group.code or group.name}: {exc}.")
            continue
        if occurrence is None:
            response.skipped_series += 1
            continue

        start_time, end_time = occurrence
        class_label = " ".join(
            part for part in [group.code.strip(), group.name.strip()] if part
        ) or "Turma"
        title = f"Aula - {group.discipline or class_label} - {class_label}"[:300]
        description = (
            f"Agenda da turma {class_label}."
            + (f" Semestre {group.semester}." if group.semester else "")
            + " Criada pelo Assistente App."
        )
        try:
            if body.provider == "google":
                event = await create_google_account_event(
                    account,
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    timezone_name=body.timezone,
                    description=description,
                    recurrence_until=body.date_to,
                )
            else:
                event = await create_microsoft_account_event(
                    account,
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    timezone_name=body.timezone,
                    description=description,
                    recurrence_until=body.date_to,
                )
            db.add(
                ClassCalendarSeriesModel(
                    fingerprint=fingerprint,
                    user_id=user["uid"],
                    tutor_id=tutor_id,
                    class_group_id=group.id,
                    class_schedule_id=schedule.id,
                    provider=body.provider,
                    account_id=body.account_id,
                    provider_event_id=event.id,
                    date_from=body.date_from.isoformat(),
                    date_to=body.date_to.isoformat(),
                    timezone_name=body.timezone,
                )
            )
            response.created_series += 1
            existing.add(fingerprint)
        except Exception as exc:
            response.failed_series += 1
            response.errors.append(f"{class_label}: {exc}")

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            "A agenda foi sincronizada simultaneamente. Atualize e tente novamente.",
        ) from exc
    return response


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
    microsoft_connected = [
        a for a in microsoft_accounts if _sanitize_account(a, "microsoft")["connected"]
    ]

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
            "configured": bool(
                microsoft_app.get("client_id") and microsoft_app.get("client_secret")
            ),
            "requires_app_registration": True,
            "accounts": [_sanitize_account(a, "microsoft") for a in microsoft_accounts],
        },
    }


@router_calendar.get("/accounts")
async def calendar_accounts(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista as contas de calendario conectadas do usuario."""
    google_accounts = await _load_google_accounts(
        db, user["uid"], include_pending=True
    )
    microsoft_accounts = await _load_microsoft_accounts(
        db, user["uid"], include_pending=True
    )
    for account in microsoft_accounts:
        if (
            not account.get("refresh_token")
            or account.get("connection_status") == "authorization_pending"
        ):
            continue
        try:
            await validate_microsoft_session(account)
        except MicrosoftAuthenticationError:
            account["connection_status"] = "reconnect_required"
            await _upsert_account(
                db,
                _KEY_MS_ACCOUNTS,
                str(account.get("id") or ""),
                {"connection_status": "reconnect_required"},
                user["uid"],
            )
        except Exception:
            # A network outage does not mean that the user's grant was revoked.
            pass
    return {
        "google": [_sanitize_account(a, "google") for a in google_accounts],
        "microsoft": [_sanitize_account(a, "microsoft") for a in microsoft_accounts],
    }


# ── Google ────────────────────────────────────────────────────────────────────

class GoogleConnectRequest(_BM):
    """Codigo de autorizacao devolvido pelo consentimento do Google."""
    client_id: str
    client_secret: str
    label: _Opt[str] = None
    account_id: _Opt[str] = None


class GoogleOAuthAppRequest(_BM):
    """Credenciais da aplicacao OAuth do Google usada na conexao."""
    client_id: str
    client_secret: str


@router_calendar.put("/google/oauth-app")
async def google_oauth_app(
    body: GoogleOAuthAppRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grava as credenciais da aplicacao OAuth do Google usada na conexao."""
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
    """Retorno de OAuth repassado pela interface ao backend."""
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
    """Recebe o retorno do consentimento do Google.

    Rota publica por necessidade: quem chama e o provedor, sem token de sessao.
    """
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
    """Desconecta todas as contas Google do usuario."""
    await _delete_config(db, _KEY_GOOGLE_ACCOUNTS, user["uid"])
    await _delete_config(db, _KEY_GOOGLE, user["uid"])
    return {"ok": True, "message": "Google Calendar desconectado."}


@router_calendar.delete("/google/accounts/{account_id}")
async def google_disconnect_account(
    account_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Desconecta uma conta Google especifica."""
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
    """Devolve a URL de consentimento do Google para a interface abrir."""
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

@router_calendar.put("/microsoft/oauth-app")
async def microsoft_oauth_app(
    user: dict = Depends(get_current_user),
):
    """Grava as credenciais da aplicacao OAuth Microsoft usada na conexao."""
    raise HTTPException(
        410,
        "A configuracao Microsoft agora pertence ao backend. O administrador "
        "deve definir MICROSOFT_OAUTH_CLIENT_ID e MICROSOFT_OAUTH_CLIENT_SECRET.",
    )


@router_calendar.get("/microsoft/start")
async def ms_start(
    request: Request,
    account_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Starts an official Microsoft browser login; secrets stay on the server."""
    app = await _load_microsoft_oauth_app(db, user["uid"])
    client_id = app.get("client_id", "")
    client_secret = app.get("client_secret", "")
    tenant_id = app.get("tenant_id") or "common"
    if not client_id or not client_secret:
        raise HTTPException(
            503,
            "A conexao Microsoft ainda nao foi configurada pelo administrador "
            "deste sistema.",
        )

    existing_accounts = await _load_microsoft_accounts(
        db, user["uid"], include_pending=True
    )
    if account_id and not any(item.get("id") == account_id for item in existing_accounts):
        raise HTTPException(404, "Conta Microsoft nao encontrada para reconexao.")
    account_id = account_id or _new_account_id("microsoft")
    redirect_uri = _oauth_redirect_uri(request, "microsoft")
    code_verifier = _secrets.token_urlsafe(64)
    code_challenge = _base64.urlsafe_b64encode(
        _hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    await _upsert_account(
        db,
        _KEY_MS_ACCOUNTS,
        account_id,
        {
            "label": next(
                (
                    item.get("label")
                    for item in existing_accounts
                    if item.get("id") == account_id
                ),
                "Microsoft",
            ),
            "redirect_uri": redirect_uri,
            "pkce_verifier": encrypt_credential(code_verifier),
            "connection_status": "authorization_pending",
        },
        user["uid"],
    )
    url = get_microsoft_auth_url(
        client_id,
        tenant_id,
        state=_oauth_state(user["uid"], "microsoft", account_id),
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
    )
    return {
        "auth_url": url,
        "account_id": account_id,
        "redirect_uri": redirect_uri,
        "next": "Open this URL and authorize the Microsoft account in the browser.",
    }


@router_calendar.post("/microsoft/connect")
async def ms_connect(
    user: dict = Depends(get_current_user),
):
    """Conclui a conexao de uma conta Microsoft a partir do codigo recebido."""
    raise HTTPException(
        410,
        "Use Conectar Microsoft. Credenciais do aplicativo nao sao aceitas pela API.",
    )


@router_calendar.post("/microsoft/callback")
async def ms_callback(
    user: dict = Depends(get_current_user),
):
    """Processa o retorno do consentimento Microsoft enviado pela interface."""
    raise HTTPException(
        410,
        "O codigo de autorizacao Microsoft e processado somente pelo callback do backend.",
    )


async def _complete_microsoft_oauth(
    request: Request,
    *,
    code: str,
    account_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict:
    """Exchanges a one-time code without ever routing it through the frontend."""
    accounts = await _load_microsoft_accounts(
        db, user_id, include_pending=True
    )
    account = _find_account(accounts, account_id)
    if not account or not account.get("pkce_verifier"):
        raise HTTPException(400, "A tentativa de conexao expirou. Inicie novamente.")
    app = await _load_microsoft_oauth_app(db, user_id)
    client_id = app.get("client_id", "")
    client_secret = app.get("client_secret", "")
    tenant_id = app.get("tenant_id") or "common"
    if not client_id or not client_secret:
        raise HTTPException(503, "A integracao Microsoft nao esta configurada.")
    redirect_uri = account.get("redirect_uri")
    if not redirect_uri:
        redirect_uri = _oauth_redirect_uri(request, "microsoft")
    token_data = await exchange_microsoft_code(
        code,
        client_id,
        client_secret,
        tenant_id,
        redirect_uri or "https://login.microsoftonline.com/common/oauth2/nativeclient",
        code_verifier=account.get("pkce_verifier"),
    )
    profile = await fetch_microsoft_profile(str(token_data["access_token"]))
    label = profile.get("display_name") or profile.get("email") or "Microsoft"
    await _upsert_account(
        db,
        _KEY_MS_ACCOUNTS,
        account_id,
        {
            "label": label,
            "redirect_uri": redirect_uri,
            "refresh_token": encrypt_credential(str(token_data["refresh_token"])),
            "pkce_verifier": None,
            "connection_status": "connected",
            **profile,
        },
        user_id,
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
    """Recebe o retorno do consentimento da Microsoft.

    Rota publica por necessidade: quem chama e o provedor, sem token de sessao.
    """
    if error:
        detail = microsoft_auth_error_message(error, error_description or "")
        if state:
            try:
                user_id, account_id = _read_oauth_state(state, "microsoft")
                await _upsert_account(
                    db,
                    _KEY_MS_ACCOUNTS,
                    account_id,
                    {"connection_status": "reconnect_required", "pkce_verifier": None},
                    user_id,
                )
            except Exception:
                pass
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
        result = await _complete_microsoft_oauth(
            request=request,
            code=code,
            account_id=account_id,
            user_id=user_id,
            db=db,
        )
    except MicrosoftAuthenticationError as exc:
        try:
            await _upsert_account(
                db,
                _KEY_MS_ACCOUNTS,
                account_id,
                {"connection_status": "reconnect_required", "pkce_verifier": None},
                user_id,
            )
        except Exception:
            pass
        return _oauth_result_page(
            "Microsoft requer atencao",
            f"{exc} Voce pode fechar esta aba.",
            ok=False,
        )
    except Exception:
        try:
            await _upsert_account(
                db,
                _KEY_MS_ACCOUNTS,
                account_id,
                {"connection_status": "reconnect_required", "pkce_verifier": None},
                user_id,
            )
        except Exception:
            pass
        return _oauth_result_page(
            "Falha ao conectar Microsoft",
            "Nao foi possivel concluir a conexao. Tente novamente; se a sua "
            "organizacao exigir aprovacao, procure o administrador Microsoft.",
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
    """Desconecta todas as contas Microsoft do usuario."""
    await _delete_config(db, _KEY_MS_ACCOUNTS, user["uid"])
    await _delete_config(db, _KEY_MS, user["uid"])
    await _delete_config(db, _KEY_MS_APP, user["uid"])
    return {"ok": True, "message": "Microsoft Calendar desconectado."}


@router_calendar.delete("/microsoft/accounts/{account_id}")
async def ms_disconnect_account(
    account_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Desconecta uma conta Microsoft especifica."""
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
    """Devolve a URL de consentimento da Microsoft para a interface abrir."""
    raise HTTPException(410, "Use /calendar/microsoft/start para iniciar o login seguro.")


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
    """Devolve as preferencias de notificacao do usuario."""
    return await _notif_cfg(db, user["uid"])


@router_notif.put("/config", response_model=NotifConfig)
async def put_notif_config(
    body: NotifConfig,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Salva as preferencias de notificacao do usuario."""
    return await save_notif_config(db, body, user_id=user["uid"])


@router_notif.post("/send", response_model=NotifResult)
async def send_notif(
    body: NotifRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Envia uma notificacao agora pelos canais configurados."""
    cfg = await _notif_cfg(db, user["uid"])
    return await send_notification(body.message, cfg, body.channels)


@router_notif.post("/test/telegram")
async def test_telegram(
    body: NotifConfig | None = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Testa a configuracao do Telegram e devolve o erro traduzido, se houver."""
    from ..services.notification_service import test_telegram_connection

    cfg = body or await _notif_cfg(db, user["uid"])
    ok, message = await test_telegram_connection(cfg)
    return {"ok": ok, "message": message}


@router_notif.post("/test/whatsapp")
async def test_whatsapp(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Testa a configuracao do WhatsApp e devolve o erro traduzido, se houver."""
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
    assistant_name: str = Form(""),
    _llm_context: None = Depends(user_llm_context),
):
    """Transcreve o audio enviado pela interface."""
    audio_bytes = await file.read()
    return await transcribe_audio(
        audio_bytes,
        language,
        assistant_name=assistant_name,
    )


@router_voice.post("/tts")
async def tts(
    body: TTSRequest,
    _llm_context: None = Depends(user_llm_context),
):
    """Sintetiza a fala do texto e devolve o audio."""
    audio = await text_to_speech(body.text, body.language, body.speed)
    return Response(content=audio, media_type="audio/mpeg")


import time
from fastapi import APIRouter
from ..models.schemas import HealthResponse
from ..services.qdrant_service import status as qdrant_status
from ..services.llm_status_service import get_llm_statuses
_gs3 = lambda: runtime_settings

router_health = APIRouter(tags=["Health"])
_start = time.time()


@router_health.get("/health", response_model=HealthResponse)
async def health():
    """Diagnostico completo: provedores, calendarios, notificacao e uptime.

    E o que alimenta os indicadores de status da interface.
    """
    s = _gs3()
    llm_status = await get_llm_statuses()
    available_llms = [
        llm for llm in s.active_llms
        if llm_status.get(llm) is not None and llm_status[llm].available
    ]
    sources = []
    return HealthResponse(
        status="ok",
        revision=build_revision(),
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
    """Checagem rasa de vida, usada pelo healthcheck do container.

    Nao toca em banco nem em servico externo de proposito: precisa responder mesmo
    com as dependencias fora do ar.
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        # Tambem aqui: e o unico health que responde com as dependencias fora
        # do ar, entao e onde da para conferir a versao de um deploy quebrado.
        "revision": build_revision(),
        "uptime_seconds": round(time.time() - _start, 1),
    }


@router_health.get("/")
async def root():
    """Identificacao da API na raiz."""
    return {"name": "assistant-backend", "version": "1.0.0", "docs": "/docs"}
