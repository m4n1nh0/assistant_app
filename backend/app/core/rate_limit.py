"""Rate limiting por IP que se desliga sozinho quando nao ha Redis.

O `fastapi-limiter` depende de Redis. Quando ele nao sobe, o backend continua
funcionando normalmente: `mark_ready(False)` deixa a dependencia inerte em vez
de derrubar todas as rotas que a declaram.
"""

from fastapi import Request, Response
from fastapi_limiter.depends import RateLimiter

_ready = False


def mark_ready(ready: bool) -> None:
    """Liga ou desliga o rate limiting no processo inteiro.

    Chamado no startup da aplicacao: `True` quando o FastAPILimiter conectou no
    Redis, `False` quando a conexao falhou.

    Args:
        ready: se o limitador esta pronto para ser usado.
    """
    global _ready
    _ready = ready


def rate_limit(times: int, seconds: int):
    """Per-IP rate limit dependency. No-ops if Redis/FastAPILimiter never initialized."""
    limiter = RateLimiter(times=times, seconds=seconds)

    async def dependency(request: Request, response: Response) -> None:
        if not _ready:
            return
        await limiter(request, response)

    return dependency
