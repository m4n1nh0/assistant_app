import asyncio
import hashlib
import hmac
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import RegistrationInviteModel

settings = get_settings()
_issue_lock = asyncio.Lock()


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
    credentials_match = bool(settings.smtp_username.strip()) == bool(
        settings.smtp_password
    )
    recipient = (
        recipient_email
        if recipient_email is not None
        else settings.registration_admin_email
    )
    return bool(
        recipient.strip()
        and settings.smtp_host.strip()
        and sender
        and credentials_match
    )


def _send_registration_email(
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

    message = EmailMessage()
    message["Subject"] = "Convite para cadastro no Assistente"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Voce recebeu um convite para criar uma conta no Assistente.\n\n"
        f"Token de uso unico:\n{token}\n\n"
        f"Valido ate {expires_at.astimezone(timezone.utc):%Y-%m-%d %H:%M UTC}.\n\n"
        "Se voce nao solicitou este token, ignore este email."
    )

    smtp_type = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
    with smtp_type(
        settings.smtp_host.strip(),
        settings.smtp_port,
        timeout=20,
    ) as smtp:
        if not settings.smtp_use_ssl and settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username.strip():
            smtp.login(settings.smtp_username.strip(), settings.smtp_password)
        smtp.send_message(message)


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
    if (
        latest is not None
        and latest.used_at is None
        and latest.revoked_at is None
        and as_utc(latest.expires_at) > now
    ):
        remaining = (as_utc(latest.expires_at) - now).total_seconds()
        raise RegistrationTokenCooldownError(max(1, int(remaining)))
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
            await asyncio.to_thread(_send_registration_email, token, expires_at)
        else:
            await asyncio.to_thread(
                _send_registration_email,
                token,
                expires_at,
                recipient,
            )
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
