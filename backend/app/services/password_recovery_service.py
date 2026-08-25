"""Recuperacao de senha por token de uso unico enviado ao email da conta.

Tres decisoes de seguranca atravessam o modulo: o banco guarda apenas o digest
do token, o pedido tem intervalo minimo entre tentativas, e a resposta e sempre
a mesma exista ou nao a conta - senao o proprio endpoint vira um verificador de
quais emails estao cadastrados.
"""

import asyncio
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import PasswordResetTokenModel, UserModel
from .registration_invite_service import (
    as_utc,
    mask_email,
    registration_delivery_configured,
    send_transactional_email,
)

settings = get_settings()
_issue_lock = asyncio.Lock()


def utc_now() -> datetime:
    """Instante atual em UTC, ponto unico de tempo do modulo."""
    return datetime.now(timezone.utc)


def password_reset_token_digest(token: str) -> str:
    """Digest do token, unica forma dele guardada no banco."""
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def _find_account(db: AsyncSession, identifier: str) -> UserModel | None:
    clean = identifier.strip()
    if not clean:
        return None
    return (
        await db.execute(
            select(UserModel).where(
                or_(
                    UserModel.username == clean,
                    func.lower(UserModel.email) == clean.lower(),
                )
            )
        )
    ).scalar_one_or_none()


async def _send_password_reset_email(
    recipient: str,
    username: str,
    token: str,
    expires_at: datetime,
) -> None:
    await send_transactional_email(
        recipient,
        subject="Recuperacao da sua conta no Assistente",
        text_content=(
            "Foi solicitada a recuperacao da sua conta no Assistente.\n\n"
            f"Usuario: {username}\n\n"
            f"Token de uso unico:\n{token}\n\n"
            f"Valido ate {expires_at.astimezone(timezone.utc):%Y-%m-%d %H:%M UTC}.\n\n"
            "Se voce nao fez esta solicitacao, ignore este email. Sua senha "
            "nao sera alterada."
        ),
    )


async def issue_password_reset_token(db: AsyncSession, identifier: str) -> bool:
    """Issues a reset token; callers must always return the same public reply."""
    async with _issue_lock:
        account = await _find_account(db, identifier)
        if (
            account is None
            or not account.is_active
            or not (account.email or "").strip()
            or not registration_delivery_configured(account.email)
        ):
            # Do the same secret-key operation used for a real token without
            # creating a row or revealing why delivery was skipped.
            password_reset_token_digest(secrets.token_urlsafe(24))
            return False

        now = utc_now()
        latest = (
            await db.execute(
                select(PasswordResetTokenModel)
                .where(PasswordResetTokenModel.user_id == account.id)
                .order_by(PasswordResetTokenModel.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        cooldown = max(0, settings.password_reset_request_cooldown_seconds)
        if latest is not None and cooldown:
            elapsed = (now - as_utc(latest.created_at)).total_seconds()
            if elapsed < cooldown:
                return False

        active = (
            await db.execute(
                select(PasswordResetTokenModel).where(
                    PasswordResetTokenModel.user_id == account.id,
                    PasswordResetTokenModel.used_at.is_(None),
                    PasswordResetTokenModel.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        for previous in active:
            previous.revoked_at = now

        token = secrets.token_urlsafe(24)
        expires_at = now + timedelta(
            minutes=max(1, settings.password_reset_token_expire_minutes)
        )
        db.add(
            PasswordResetTokenModel(
                user_id=account.id,
                token_hash=password_reset_token_digest(token),
                expires_at=expires_at,
            )
        )
        try:
            await db.flush()
            await _send_password_reset_email(
                account.email,
                account.username,
                token,
                expires_at,
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Password recovery email failed for "
                f"{mask_email(account.email)}: {type(exc).__name__}"
            )
            return False

        logger.info(f"Password recovery token sent to {mask_email(account.email)}")
        return True


async def consume_password_reset_token(
    db: AsyncSession,
    token: str,
    password_hash: str,
) -> bool:
    """Valida o token e troca a senha, invalidando as sessoes abertas.

    O token e queimado no uso e a versao de autenticacao da conta e incrementada,
    o que derruba qualquer JWT emitido antes.
    """
    clean = token.strip()
    if not clean:
        return False
    reset = (
        await db.execute(
            select(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.token_hash
                == password_reset_token_digest(clean),
                PasswordResetTokenModel.used_at.is_(None),
                PasswordResetTokenModel.revoked_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if reset is None or as_utc(reset.expires_at) <= utc_now():
        return False

    account = await db.get(UserModel, reset.user_id)
    if account is None or not account.is_active:
        return False

    account.password_hash = password_hash
    account.auth_version = int(account.auth_version or 0) + 1
    reset.used_at = utc_now()
    await db.commit()
    return True
