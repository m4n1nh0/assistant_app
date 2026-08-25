"""Identificacao do cliente real quando o backend roda atras de proxy reverso."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """Real client IP behind a reverse proxy (Railway, etc.), falling back to the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def client_ip_identifier(request: Request) -> str:
    """Versao assincrona de `client_ip`, na assinatura que o fastapi-limiter espera.

    Args:
        request: requisicao em curso.

    Returns:
        O IP usado como chave do rate limiting por cliente.
    """
    return client_ip(request)
