import asyncio
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import RegistrationInviteModel

settings = get_settings()
_issue_lock = asyncio.Lock()

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_ACCOUNT_URL = "https://api.brevo.com/v3/account"


class RegistrationDeliveryError(Exception):
    pass


class RegistrationTokenCooldownError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Aguarde {retry_after_seconds} segundos antes de solicitar outro token."
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def registration_token_digest(token: str) -> str:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mask_email(email: str) -> str:
    local, separator, domain = email.strip().partition("@")
    if not separator or not local or not domain:
        return ""
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def registration_delivery_configured(recipient_email: str | None = None) -> bool:
    sender = settings.smtp_from.strip() or settings.smtp_username.strip()
    recipient = (
        recipient_email
        if recipient_email is not None
        else settings.registration_admin_email
    )
    return bool(
        recipient.strip()
        and settings.brevo_api_key.strip()
        and sender
    )


async def _send_registration_email(
    token: str,
    expires_at: datetime,
    recipient_email: str | None = None,
) -> None:
    recipient = (
        recipient_email
        if recipient_email is not None
        else settings.registration_admin_email
    ).strip()
    sender = settings.smtp_from.strip() or settings.smtp_username.strip()

    payload = {
        "sender": {"email": sender},
        "to": [{"email": recipient}],
        "subject": "Convite para cadastro no Assistente",
        "textContent": (
            "Voce recebeu um convite para criar uma conta no Assistente.\n\n"
            f"Token de uso unico:\n{token}\n\n"
            f"Valido ate {expires_at.astimezone(timezone.utc):%Y-%m-%d %H:%M UTC}.\n\n"
            "Se voce nao solicitou este token, ignore este email."
        ),
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            BREVO_SEND_URL,
            headers={
                "api-key": settings.brevo_api_key.strip(),
                "content-type": "application/json",
                "accept": "application/json",
            },
            json=payload,
        )
    response.raise_for_status()


async def brevo_api_diagnostic() -> dict:
    """One-off connectivity check for the Brevo API key. Sends no email."""
    result = {"api_key_set": bool(settings.brevo_api_key.strip()), "success": False}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                BREVO_ACCOUNT_URL,
                headers={
                    "api-key": settings.brevo_api_key.strip(),
                    "accept": "application/json",
                },
            )
        result["status_code"] = response.status_code
        response.raise_for_status()
        result["success"] = True
        result["email"] = response.json().get("email")
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
    return result


async def issue_registration_token(
    db: AsyncSession,
    recipient_email: str | None = None,
    invited_by: str | None = None,
    role: str | None = None,
) -> tuple[str, datetime]:
    async with _issue_lock:
        return await _issue_registration_token(
            db,
            recipient_email=recipient_email,
            invited_by=invited_by,
            role=role,
        )


async def _issue_registration_token(
    db: AsyncSession,
    recipient_email: str | None = None,
    invited_by: str | None = None,
    role: str | None = None,
) -> tuple[str, datetime]:
    recipient = (
        recipient_email
        if recipient_email is not None
        else settings.registration_admin_email
    ).strip().lower()
    invite_role = role or ("user" if invited_by else "admin")
    if not registration_delivery_configured(recipient):
        raise RegistrationDeliveryError(
            "Envio de email de convite nao configurado no backend."
        )

    now = utc_now()
    latest_result = await db.execute(
        select(RegistrationInviteModel)
        .where(RegistrationInviteModel.recipient_email == recipient)
        .order_by(RegistrationInviteModel.created_at.desc())
        .limit(1)
    )
    latest = latest_result.scalar_one_or_none()
    cooldown = max(0, settings.registration_token_request_cooldown_seconds)
    if latest is not None and cooldown:
        elapsed = (now - as_utc(latest.created_at)).total_seconds()
        if elapsed < cooldown:
            raise RegistrationTokenCooldownError(
                max(1, int(cooldown - elapsed))
            )

    active_result = await db.execute(
        select(RegistrationInviteModel).where(
            RegistrationInviteModel.recipient_email == recipient,
            RegistrationInviteModel.used_at.is_(None),
            RegistrationInviteModel.revoked_at.is_(None),
        )
    )
    for invite in active_result.scalars().all():
        invite.revoked_at = now

    token = secrets.token_urlsafe(24)
    expires_at = now + timedelta(
        minutes=max(1, settings.registration_token_expire_minutes)
    )
    invite = RegistrationInviteModel(
        token_hash=registration_token_digest(token),
        recipient_email=recipient,
        role=invite_role,
        invited_by=invited_by,
        expires_at=expires_at,
    )
    db.add(invite)

    try:
        await db.flush()
        if recipient_email is None:
            await _send_registration_email(token, expires_at)
        else:
            await _send_registration_email(token, expires_at, recipient)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(f"Registration token email failed: {type(exc).__name__}")
        raise RegistrationDeliveryError(
            "Nao foi possivel enviar o token administrativo por email."
        ) from exc

    logger.info(
        f"Registration token sent to {mask_email(recipient)}"
    )
    return mask_email(recipient), expires_at


async def lock_registration_invite(
    db: AsyncSession,
    token: str,
) -> RegistrationInviteModel | None:
    clean_token = token.strip()
    if not clean_token:
        return None

    result = await db.execute(
        select(RegistrationInviteModel)
        .where(
            RegistrationInviteModel.token_hash
            == registration_token_digest(clean_token),
            RegistrationInviteModel.used_at.is_(None),
            RegistrationInviteModel.revoked_at.is_(None),
        )
        .with_for_update()
    )
    invite = result.scalar_one_or_none()
    if invite is None or as_utc(invite.expires_at) <= utc_now():
        return None
    return invite
