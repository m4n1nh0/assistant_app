"""Middleware e bootstrap da observabilidade da aplicacao.

O middleware e o unico lugar que *cria* um contexto de correlacao: toda
requisicao entra por aqui, recebe ou herda `X-Request-ID` e `traceparent`, e a
partir dai qualquer camada le o contexto sem receber parametro extra.

O identificador tambem volta na resposta. Sem isso o usuario que relata um erro
nao tem como dizer qual execucao falhou, e o log vira busca por horario.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from ...ports.telemetry import SpanRecord
from .context import (
    REQUEST_ID_HEADER,
    ObservabilityContext,
    context_from_headers,
    current_context,
    reset_context,
    set_context,
)
from .costs import load_pricing_overrides
from .tracing import configure_sink, default_sink, get_sink


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Abre o contexto de correlacao e mede a requisicao.

    Nao substitui o log de acesso que ja existe: aquele e legivel por humano,
    este alimenta o trace. Os dois convivem porque respondem perguntas
    diferentes.
    """

    def __init__(self, app, *, excluded_paths: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self._excluded = excluded_paths

    async def dispatch(self, request: Request, call_next):
        context = context_from_headers(dict(request.headers))
        token = set_context(context)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = context.request_id
            traceparent = context.traceparent()
            if traceparent:
                response.headers["traceparent"] = traceparent
            return response
        finally:
            if request.url.path not in self._excluded:
                _record_request(
                    request.method,
                    request.scope.get("route").path
                    if request.scope.get("route") is not None
                    else request.url.path,
                    status_code,
                    (time.perf_counter() - started) * 1000,
                    context,
                )
            reset_context(token)


def _record_request(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    context: ObservabilityContext,
) -> None:
    try:
        get_sink().record_span(
            SpanRecord(
                name=f"{method} {path}",
                kind="http",
                duration_ms=round(duration_ms, 3),
                ok=status_code < 500,
                attributes={"http.method": method, "http.status_code": status_code},
                correlation=context.as_dict(),
            )
        )
    except Exception:
        pass


def setup_observability(
    app: FastAPI | None,
    *,
    service_name: str,
    settings,
    excluded_paths: tuple[str, ...] = ("/health", "/health/live"),
) -> None:
    """Liga a observabilidade de um processo.

    Chamado por cada entrypoint - assistant-api, tool-service, mcp-service -
    com o nome do proprio servico, para que os spans dos tres apareçam sob o
    mesmo trace mas identificados separadamente.

    Args:
        app: aplicacao FastAPI que recebe o middleware; `None` para processos
            sem HTTP.
        service_name: nome do servico no trace.
        settings: configuracao ja carregada.
        excluded_paths: rotas que nao geram span (healthcheck de container).
    """
    sink, memory = default_sink(
        memory_events=getattr(settings, "telemetry_memory_events", 2000)
    )
    configure_sink(sink, memory=memory)
    load_pricing_overrides(getattr(settings, "llm_pricing", ""))

    if getattr(settings, "otel_enabled", False):
        from .otel import setup as setup_otel

        setup_otel(
            service_name=service_name,
            endpoint=getattr(settings, "otel_exporter_endpoint", ""),
            console=getattr(settings, "otel_console_export", False),
        )

    from .langsmith import setup as setup_langsmith

    setup_langsmith(
        enabled=getattr(settings, "langsmith_enabled", False),
        api_key=getattr(settings, "langsmith_api_key", ""),
        project=getattr(settings, "langsmith_project", ""),
        endpoint=getattr(settings, "langsmith_endpoint", ""),
    )

    if app is not None:
        app.add_middleware(CorrelationMiddleware, excluded_paths=excluded_paths)
    logger.info(f"Observabilidade pronta para {service_name}")


def shutdown_observability() -> None:
    """Descarrega spans pendentes no encerramento do processo."""
    try:
        from .otel import shutdown

        shutdown()
    except Exception:
        pass


def log_prefix() -> str:
    """Identificadores do contexto ativo, prontos para concatenar num log."""
    context = current_context()
    return " ".join(f"{key}={value}" for key, value in context.as_dict().items())
