"""Esqueleto compartilhado pelos servicos extraidos.

Todo servico independente precisa das mesmas cinco coisas: observabilidade
ligada, contexto de correlacao propagado, `live` e `ready` separados,
encerramento gracioso e porta vinda da configuracao. Repetir isso em cada
entrypoint garantiria que um deles ficasse diferente dos outros.

A distincao entre `live` e `ready` e proposital e nao decorativa: `live` diz que
o processo esta de pe (o orquestrador de container nao deve mata-lo), `ready`
diz que ele consegue atender (o cliente pode mandar trabalho). Um mcp-service
com todos os servidores fora do ar esta vivo e nao esta pronto - e responder
`200` nos dois casos faria o cliente insistir num servico que nao vai atender.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from loguru import logger

from app.core.config import get_settings
from app.core.observability.middleware import (
    setup_observability,
    shutdown_observability,
)

ReadyCheck = Callable[[], Awaitable[dict[str, Any]]]


def create_service(
    *,
    name: str,
    title: str,
    description: str,
    ready_check: ReadyCheck | None = None,
    on_startup: Callable[[], Awaitable[None]] | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    """Monta um servico com ciclo de vida, health e observabilidade.

    Args:
        name: nome usado no trace e no log (`mcp-service`, `tool-service`).
        title: titulo exibido na documentacao OpenAPI.
        description: descricao do servico na documentacao.
        ready_check: verificacao de prontidao; devolve um dicionario com pelo
            menos `ok`.
        on_startup: trabalho extra na subida.
        on_shutdown: liberacao de recurso no encerramento.

    Returns:
        A aplicacao FastAPI pronta para o uvicorn.
    """
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(f"{name} iniciando")
        if on_startup is not None:
            try:
                await on_startup()
            except Exception as exc:
                # Servico sobe mesmo com dependencia fora do ar; quem responde
                # por isso e o `ready`, nao o boot.
                logger.warning(f"{name}: inicializacao parcial: {exc}")
        yield
        if on_shutdown is not None:
            try:
                await on_shutdown()
            except Exception as exc:
                logger.warning(f"{name}: encerramento com erro: {exc}")
        shutdown_observability()
        logger.info(f"{name} encerrado")

    app = FastAPI(
        title=title,
        description=description,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
    )
    setup_observability(
        app,
        service_name=name,
        settings=settings,
        excluded_paths=("/health/live", "/health/ready"),
    )

    @app.get("/health/live", include_in_schema=False)
    async def health_live() -> dict[str, Any]:
        """Diz que o processo esta de pe. Nao consulta dependencia alguma."""
        return {"status": "alive", "service": name}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, Any]:
        """Diz se o servico consegue atender agora."""
        if ready_check is None:
            return {"ok": True, "service": name}
        try:
            result = await ready_check()
        except Exception as exc:
            return {"ok": False, "service": name, "error": str(exc)}
        return {"service": name, **result}

    return app


def resolve_port(configured: int) -> int:
    """Porta em que este processo deve escutar.

    `PORT` vence quando existe. Quem injeta essa variavel e a plataforma
    (Railway, Render, Fly), e e para ela que o roteador manda o trafego - um
    servico dedicado que escutasse na porta do `Settings` ficaria inalcancavel e
    reprovaria no healthcheck sem mensagem util.

    Localmente, onde `PORT` nao existe, vale a porta especifica do servico
    (`MCP_SERVICE_PORT`, `TOOL_SERVICE_PORT`, `ORCHESTRATOR_PORT`), que e o que
    permite subir os tres lado a lado.

    Args:
        configured: porta vinda do `Settings` daquele servico.

    Returns:
        A porta efetiva. Valor invalido em `PORT` cai para a configurada, em vez
        de derrubar o boot por causa de uma variavel malformada.
    """
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return configured
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"PORT invalido ({raw!r}); usando {configured}")
        return configured


def serve(app_path: str, *, port: int, host: str = "0.0.0.0") -> None:
    """Sobe o servico com uvicorn na porta efetiva.

    A porta nunca e literal no codigo: vem da configuracao ou da plataforma, e o
    valor em `Settings` e so um padrao de desenvolvimento.
    """
    import uvicorn

    settings = get_settings()
    resolved = resolve_port(port)
    logger.info(f"{app_path} escutando em {host or settings.host}:{resolved}")
    uvicorn.run(
        app_path,
        host=host or settings.host,
        port=resolved,
        reload=settings.reload,
        log_level=settings.log_level,
    )
