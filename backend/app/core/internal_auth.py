"""Autenticacao das rotas entre servicos.

Usuario prova quem e com JWT; servico prova com um segredo compartilhado, em
`X-Internal-Token`. As duas coisas nao se misturam: o orquestrador nao age em
nome de um usuario logado, ele atende a assistant-api, que ja autenticou.

Token nao configurado **fecha** a rota. Parece rigido, mas a alternativa e pior:
a rota interna da API leva chamada ate a maquina do usuario e mora no mesmo
dominio publico do produto - um padrao aberto transformaria um esquecimento de
variavel em execucao remota.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


def internal_headers() -> dict[str, str]:
    """Cabecalho de autenticacao para chamar outro servico interno."""
    token = get_settings().internal_service_token.strip()
    return {INTERNAL_TOKEN_HEADER: token} if token else {}


def internal_token_matches(provided: str | None) -> bool:
    """Compara o token recebido com o configurado, em tempo constante."""
    expected = get_settings().internal_service_token.strip()
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.strip(), expected)


async def require_internal_token(
    x_internal_token: str | None = Header(default=None, alias=INTERNAL_TOKEN_HEADER),
) -> None:
    """Dependencia de rota: so passa quem apresenta o segredo interno.

    Raises:
        HTTPException: 503 quando o token nao esta configurado neste processo,
            401 quando o recebido nao confere.
    """
    if not get_settings().internal_service_token.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTERNAL_SERVICE_TOKEN nao configurado neste servico",
        )
    if not internal_token_matches(x_internal_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token interno invalido",
        )
