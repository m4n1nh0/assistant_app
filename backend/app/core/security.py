from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import UserModel, get_db

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_secret(secret: str) -> str:
    return pwd_context.hash(secret)


def verify_secret(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload.update({"exp": expire})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def resolve_token_user(token: str, db: AsyncSession) -> dict:
    payload = decode_token(token)
    user_id = str(payload.get("uid") or "").strip()
    username = str(payload.get("sub") or "").strip()
    if user_id:
        account = await db.get(UserModel, user_id)
    elif username:
        account = (
            await db.execute(
                select(UserModel).where(UserModel.username == username)
            )
        ).scalar_one_or_none()
    else:
        account = None

    if account is None or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Conta inexistente ou desativada",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not account.tutor_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conta sem perfil de dados vinculado",
        )
    return {
        **payload,
        "sub": account.username,
        "uid": account.id,
        "email": account.email,
        "role": account.role or "user",
        "tutor_id": account.tutor_id,
    }


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    return await resolve_token_user(credentials.credentials, db)


async def get_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[dict]:
    if not credentials:
        return None
    try:
        return await resolve_token_user(credentials.credentials, db)
    except HTTPException:
        return None


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem realizar esta acao",
        )
    return user


def account_token(account: UserModel) -> str:
    return create_token(
        {
            "sub": account.username,
            "uid": account.id,
            "role": account.role or "user",
            "tutor_id": account.tutor_id,
        }
    )
