"""Autenticacao: hash de senha, emissao/validacao de JWT e dependencias de rota.

O token carrega `uid`, `sub` (username), `role`, `tutor_id` e `ver`. O `ver` e
comparado com `auth_version` da conta a cada requisicao, o que permite invalidar
todas as sessoes de um usuario incrementando um contador no banco.
"""

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
    """Gera o hash bcrypt de uma senha ou token de uso unico.

    Args:
        secret: valor em texto puro.

    Returns:
        Hash no formato do passlib, pronto para persistir.
    """
    return pwd_context.hash(secret)


def verify_secret(plain: str, hashed: str) -> bool:
    """Confere um valor em texto puro contra o hash guardado.

    Args:
        plain: valor informado pelo usuario.
        hashed: hash lido do banco.

    Returns:
        `True` quando conferem.
    """
    return pwd_context.verify(plain, hashed)


def create_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Assina um JWT com os dados informados e uma expiracao.

    Args:
        data: claims a incluir no token (`sub`, `uid`, `role`, `tutor_id`, `ver`).
        expires_delta: validade customizada; sem ela vale `jwt_expire_minutes`.

    Returns:
        O token assinado.
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload.update({"exp": expire})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decodifica e valida a assinatura de um JWT.

    Args:
        token: token recebido no cabecalho `Authorization`.

    Returns:
        As claims do token.

    Raises:
        HTTPException: 401 quando o token e invalido ou expirou.
    """
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
    """Resolve o token em uma conta ativa e devolve o contexto do usuario.

    Alem de validar a assinatura, confere no banco que a conta existe, esta ativa,
    que a versao de autenticacao do token ainda vale e que ha perfil de dados
    vinculado - checagens que o JWT sozinho nao garante.

    Args:
        token: JWT recebido na requisicao.
        db: sessao do banco.

    Returns:
        As claims enriquecidas com `sub`, `uid`, `email`, `role` e `tutor_id` lidos
        da conta.

    Raises:
        HTTPException: 401 para token invalido, conta inexistente/desativada ou
            sessao invalidada; 409 quando a conta nao tem perfil de dados.
    """
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
    if int(payload.get("ver") or 0) != int(account.auth_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessao invalidada. Entre novamente.",
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
    """Dependencia de rota que exige autenticacao.

    Returns:
        O contexto do usuario autenticado.

    Raises:
        HTTPException: 401 quando nao ha cabecalho `Authorization` ou o token nao
            resolve em conta valida.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    return await resolve_token_user(credentials.credentials, db)


async def get_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[dict]:
    """Dependencia de rota que aceita requisicao anonima.

    Returns:
        O contexto do usuario, ou `None` quando nao ha token ou ele nao vale. Nunca
        levanta - use em rota que muda de comportamento, e nao bloqueia, sem login.
    """
    if not credentials:
        return None
    try:
        return await resolve_token_user(credentials.credentials, db)
    except HTTPException:
        return None


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependencia de rota restrita a administradores.

    Returns:
        O contexto do usuario administrador.

    Raises:
        HTTPException: 403 quando a conta autenticada nao tem `role` admin.
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem realizar esta acao",
        )
    return user


def account_token(account: UserModel) -> str:
    """Emite o JWT de sessao de uma conta ja autenticada.

    Args:
        account: registro da conta no banco.

    Returns:
        Token com as claims de identidade, papel, perfil de dados e a versao de
        autenticacao corrente.
    """
    return create_token(
        {
            "sub": account.username,
            "uid": account.id,
            "role": account.role or "user",
            "tutor_id": account.tutor_id,
            "ver": int(account.auth_version or 0),
        }
    )
