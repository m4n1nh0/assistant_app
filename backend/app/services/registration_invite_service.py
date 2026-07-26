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


def registration_delivery_configured() -> bool:
    sender = settings.smtp_from.strip() or settings.smtp_username.strip()
    credentials_match = bool(settings.smtp_username.strip()) == bool(
        settings.smtp_password
    )
    return bool(
        settings.registration_admin_email.strip()
        and settings.smtp_host.strip()
        and sender
        and credentials_match
    )


def _send_registration_email(token: str, expires_at: datetime) -> None:
    recipient = settings.registration_admin_email.strip()
    sender = settings.smtp_from.strip() or settings.smtp_username.strip()

    message = EmailMessage()
    message["Subject"] = "Token administrativo para cadastro"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Foi solicitado o cadastro inicial do Assistente.\n\n"
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


async def issue_registration_token(db: AsyncSession) -> tuple[str, datetime]:
    async with _issue_lock:
        return await _issue_registration_token(db)


async def _issue_registration_token(db: AsyncSession) -> tuple[str, datetime]:
    if not registration_delivery_configured():
        raise RegistrationDeliveryError(
            "Envio de email administrativo nao configurado no backend."
        )

    now = utc_now()
    latest_result = await db.execute(
        select(RegistrationInviteModel)
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
        recipient_email=settings.registration_admin_email.strip(),
        expires_at=expires_at,
    )
    db.add(invite)

    try:
        await db.flush()
        await asyncio.to_thread(_send_registration_email, token, expires_at)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(f"Registration token email failed: {type(exc).__name__}")
        raise RegistrationDeliveryError(
            "Nao foi possivel enviar o token administrativo por email."
        ) from exc

    logger.info(
        "Registration token sent to "
        f"{mask_email(settings.registration_admin_email)}"
    )
    return mask_email(settings.registration_admin_email), expires_at


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
