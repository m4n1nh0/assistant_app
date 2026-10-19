"""Ligacao opcional com o OpenTelemetry.

Todo o modulo e defensivo de proposito: o pacote `opentelemetry-sdk` nao e
obrigatorio para rodar o backend. Sem ele, `start_span` devolve `None` e a
abstracao de tracing segue funcionando so com log e memoria.

A escolha do exporter e do endpoint fica no ambiente (`OTEL_EXPORTER_OTLP_*`),
que e o padrao da propria especificacao - nao ha nome de fornecedor no codigo.
"""

from __future__ import annotations

import importlib
from typing import Any

from loguru import logger

from shared.ports.telemetry import SpanKind, SpanRecord

_tracer: Any = None
_enabled = False
_meter_provider: Any = None
_instruments: dict[str, Any] = {}

_KIND_TO_ATTRIBUTE = "assistant.span.kind"


def signal_url(endpoint: str, signal: str) -> str:
    """Endpoint OTLP/HTTP de um sinal (`traces` ou `metrics`).

    Com endpoint explicito o SDK usa a URL como veio, sem acrescentar `/v1/traces`. Aceita aqui
    tanto a base (`http://collector:4318`) quanto a URL completa de um dos sinais, e devolve a
    do sinal pedido, para um valor so servir a traces e a metricas.
    """
    base = endpoint.strip().rstrip("/")
    for known in ("/v1/traces", "/v1/metrics", "/v1/logs"):
        if base.endswith(known):
            base = base[: -len(known)]
            break
    return f"{base}/v1/{signal}"


def available() -> bool:
    """Diz se o SDK do OpenTelemetry esta instalado e configurado."""
    return _enabled


def setup(
    *,
    service_name: str,
    endpoint: str = "",
    console: bool = False,
) -> bool:
    """Inicializa o tracer provider e o exporter OTLP.

    Args:
        service_name: nome do servico no trace (`assistant-api`, `mcp-service`...).
        endpoint: endpoint OTLP/HTTP; vazio usa o padrao do proprio SDK.
        console: tambem imprime spans no stdout, util em desenvolvimento.

    Returns:
        `True` quando o tracing distribuido ficou ativo. Ausencia do pacote ou
        falha de configuracao devolve `False` com warning, nunca excecao: o
        backend precisa subir mesmo sem coletor.
    """
    global _tracer, _enabled
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.info(
            "OpenTelemetry nao instalado: tracing segue em log e memoria. "
            "Instale opentelemetry-sdk para exportar traces."
        )
        return False

    try:
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        exporters = []
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporters.append(
                OTLPSpanExporter(endpoint=signal_url(endpoint, "traces"))
                if endpoint
                else OTLPSpanExporter()
            )
        except ImportError:
            logger.warning(
                "Exporter OTLP ausente: spans ficam so no processo. "
                "Instale opentelemetry-exporter-otlp-proto-http."
            )
        if console:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            exporters.append(ConsoleSpanExporter())

        for exporter in exporters:
            provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        _enabled = True
        _setup_metrics(service_name=service_name, endpoint=endpoint)
        logger.info(
            f"OpenTelemetry ativo para {service_name}. O exporter OTLP precisa "
            "de um collector alcancavel: sem ele, o SDK registra falha de envio "
            "a cada lote. Deixe OTEL_ENABLED=false quando nao houver collector."
        )
        return True
    except Exception as exc:
        logger.warning(f"OpenTelemetry indisponivel: {exc}")
        _tracer = None
        _enabled = False
        return False


def peer_service_hooks(peers: dict[str, str]) -> tuple[Any, Any]:
    """Ganchos do cliente HTTP que rotulam a chamada com o nome do servico de destino.

    O mapa de servicos nomeia o destino pelo host quando o servidor dele nao devolve span (as
    rotas de health, por exemplo, nao geram). No Railway o host e o nome do servico, e o nome
    gerado ("serene-creation") nao diz o papel dele. A aplicacao sabe qual URL e de qual servico
    (`TOOL_SERVICE_URL`, `ORCHESTRATOR_URL`...), entao o rotulo sai dela, sem apelido manual.

    Args:
        peers: host (minusculo) -> nome do servico.

    Returns:
        O gancho sincrono e o assincrono, na forma que o instrumentador do httpx espera.
    """
    def label(span: Any, request: Any) -> None:
        try:
            name = peers.get(str(request.url.host).lower())
            if name:
                span.set_attribute("peer.service", name)
        except Exception:
            pass  # rotulo e acessorio: nunca pode quebrar a chamada

    async def label_async(span: Any, request: Any) -> None:
        label(span, request)

    return label, label_async


def instrument_clients(
    *, tracer_provider: Any = None, peers: dict[str, str] | None = None
) -> list[str]:
    """Liga o trace nas chamadas que saem deste processo.

    Cada chamada HTTP (outro servico, Qdrant, provedor de modelo) e cada comando do Redis vira um
    span de CLIENTE, e as chamadas HTTP levam o `traceparent` junto. E isso que liga o trace da API
    ao do orquestrador, da tool-service e do MCP, e e o que o mapa de servicos do collector precisa
    para desenhar quem chama quem.

    Args:
        tracer_provider: provedor de traces; `None` usa o global.
        peers: host -> nome dos nossos servicos (veja `peer_service_hooks`).

    Returns:
        Os nomes do que foi ligado. Pacote ausente nao e erro: aquele pedaco so fica de fora.
    """
    if not _enabled:
        return []
    ligados: list[str] = []
    for nome, modulo, classe in (
        ("httpx", "opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
        ("redis", "opentelemetry.instrumentation.redis", "RedisInstrumentor"),
    ):
        try:
            instrumentor = getattr(importlib.import_module(modulo), classe)()
            if not instrumentor.is_instrumented_by_opentelemetry:
                options: dict[str, Any] = {"tracer_provider": tracer_provider}
                if nome == "httpx" and peers:
                    hook, async_hook = peer_service_hooks(peers)
                    options.update(request_hook=hook, async_request_hook=async_hook)
                instrumentor.instrument(**options)
            ligados.append(nome)
        except ImportError:
            logger.debug(f"Instrumentacao de {nome} ausente: sem spans de cliente para ele.")
        except Exception as exc:
            logger.warning(f"Instrumentacao de {nome} falhou: {exc}")
    return ligados


def instrument_database(engine: Any) -> bool:
    """Liga o trace nas consultas do engine SQLAlchemy (um span de cliente por comando)."""
    if not _enabled:
        return False
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))
        return True
    except ImportError:
        logger.debug("Instrumentacao de SQLAlchemy ausente: o banco nao aparece no mapa.")
    except Exception as exc:
        logger.warning(f"Instrumentacao do banco falhou: {exc}")
    return False


def instrument_server(
    app: Any, *, excluded_paths: tuple[str, ...] = (), tracer_provider: Any = None
) -> bool:
    """Abre um span de SERVIDOR para cada requisicao que entra, herdando o `traceparent` recebido.

    Sem isso o servico que recebe a chamada abre um trace novo, e a API e o orquestrador viram
    dois traces sem ligacao.
    """
    if not _enabled or app is None:
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=",".join(p.lstrip("/") for p in excluded_paths) or None,
            tracer_provider=tracer_provider,
        )
        return True
    except ImportError:
        logger.debug("Instrumentacao do FastAPI ausente: sem spans de servidor.")
    except Exception as exc:
        logger.warning(f"Instrumentacao do servidor falhou: {exc}")
    return False


def shutdown() -> None:
    """Descarrega os spans pendentes no encerramento do processo."""
    if not _enabled:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        pass
    if _meter_provider is not None:
        try:
            _meter_provider.shutdown()
        except Exception:
            pass


# --- Metricas ------------------------------------------------------------------------------
#
# Os rotulos sao so os de baixa cardinalidade (provedor, modelo, rota, status): conversa,
# requisicao e execucao ficam nos traces. Um rotulo por conversa criaria uma serie por
# conversa, e o backend de metricas pagaria por isso.

_EXPORT_INTERVAL_MS = 15_000

# Faixas dos histogramas de duracao, em ms. As do SDK terminam em 10 s: uma chamada de modelo que
# leva 30 s cai no balde "acima de tudo", e o p95 fica preso em 10 s no grafico (parece que nada
# demora mais que isso). Estas cobrem de meio segundo a dois minutos, que e onde uma chamada a
# modelo de linguagem de fato varia.
LLM_DURATION_BUCKETS_MS = (250, 500, 1_000, 2_500, 5_000, 10_000, 20_000, 30_000, 60_000, 120_000)
HTTP_DURATION_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000, 120_000)


def _setup_metrics(*, service_name: str, endpoint: str, reader: Any = None) -> bool:
    """Liga o exportador de metricas OTLP. `reader` existe para os testes injetarem um leitor."""
    global _meter_provider
    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
        from opentelemetry.sdk.resources import Resource

        if reader is None:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            exporter = (
                OTLPMetricExporter(endpoint=signal_url(endpoint, "metrics"))
                if endpoint
                else OTLPMetricExporter()
            )
            reader = PeriodicExportingMetricReader(
                exporter, export_interval_millis=_EXPORT_INTERVAL_MS
            )
        provider = MeterProvider(
            resource=Resource.create({"service.name": service_name}),
            metric_readers=[reader],
            views=[
                View(
                    instrument_name="assistant.llm.duration",
                    aggregation=ExplicitBucketHistogramAggregation(LLM_DURATION_BUCKETS_MS),
                ),
                View(
                    instrument_name="assistant.http.request.duration",
                    aggregation=ExplicitBucketHistogramAggregation(HTTP_DURATION_BUCKETS_MS),
                ),
            ],
        )
        meter = provider.get_meter(service_name)
        _instruments.clear()
        _instruments["tokens"] = meter.create_counter(
            "assistant.llm.tokens",
            unit="{token}",
            description="Tokens das chamadas a modelos, por tipo (input, output, cached).",
        )
        _instruments["cost"] = meter.create_counter(
            "assistant.llm.cost.usd",
            description="Custo estimado das chamadas a modelos, em dolares.",
        )
        _instruments["calls"] = meter.create_counter(
            "assistant.llm.calls",
            unit="{call}",
            description="Chamadas a modelos, por resultado.",
        )
        _instruments["llm_duration"] = meter.create_histogram(
            "assistant.llm.duration",
            unit="ms",
            description="Duracao das chamadas a modelos.",
        )
        _instruments["http_duration"] = meter.create_histogram(
            "assistant.http.request.duration",
            unit="ms",
            description="Duracao das requisicoes HTTP, por rota.",
        )
        _meter_provider = provider
        metrics.set_meter_provider(provider)
        return True
    except ImportError:
        logger.warning(
            "Exporter OTLP de metricas ausente: so traces serao exportados. "
            "Instale opentelemetry-exporter-otlp-proto-http."
        )
    except Exception as exc:
        logger.warning(f"Metricas OpenTelemetry indisponiveis: {exc}")
    _instruments.clear()
    return False


def record_usage_metrics(usage: Any) -> None:
    """Conta tokens, custo, chamadas e duracao de uma chamada a modelo."""
    if not _instruments:
        return
    try:
        labels = {"provider": usage.provider, "model": usage.model or "desconhecido"}
        for kind, value in (
            ("input", usage.input_tokens),
            ("output", usage.output_tokens),
            ("cached", usage.cached_tokens),
        ):
            # `None` e "o provedor nao informou": nao vira zero, para a soma nao fingir um dado.
            if value:
                _instruments["tokens"].add(value, {**labels, "type": kind})
        if usage.estimated_cost_usd:
            _instruments["cost"].add(usage.estimated_cost_usd, labels)
        _instruments["calls"].add(1, {**labels, "ok": "true" if usage.ok else "false"})
        _instruments["llm_duration"].record(usage.duration_ms, labels)
    except Exception:
        pass


def record_http_metric(method: str, route: str, status_code: int, duration_ms: float) -> None:
    """Mede uma requisicao HTTP. `route` e o padrao da rota, nao o caminho com ids."""
    if not _instruments:
        return
    try:
        _instruments["http_duration"].record(
            duration_ms,
            {"http.method": method, "http.route": route, "http.status_code": status_code},
        )
    except Exception:
        pass


def start_span(name: str, kind: SpanKind, attributes: dict[str, Any]):
    """Abre um span do OTel, ou `None` quando o tracing esta desligado."""
    if not _enabled or _tracer is None:
        return None
    try:
        span = _tracer.start_as_current_span(name)
        entered = span.__enter__()
        entered.set_attribute(_KIND_TO_ATTRIBUTE, kind)
        for key, value in attributes.items():
            _set_attribute(entered, key, value)
        return _SpanScope(span, entered)
    except Exception:
        return None


def finish_span(scope: Any, record: SpanRecord) -> None:
    """Fecha o span do OTel copiando o que foi descoberto durante a operacao."""
    if not isinstance(scope, _SpanScope):
        return
    try:
        for key, value in record.attributes.items():
            _set_attribute(scope.span, key, value)
        for key, value in record.correlation.items():
            _set_attribute(scope.span, f"assistant.{key}", value)
        if record.retries:
            scope.span.set_attribute("assistant.retries", record.retries)
        if not record.ok:
            from opentelemetry.trace import Status, StatusCode

            scope.span.set_status(Status(StatusCode.ERROR, record.error))
    except Exception:
        pass
    finally:
        try:
            scope.manager.__exit__(None, None, None)
        except Exception:
            pass


class _SpanScope:
    """Guarda o context manager e o span, para fechar o par no fim."""

    __slots__ = ("manager", "span")

    def __init__(self, manager: Any, span: Any) -> None:
        self.manager = manager
        self.span = span

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _set_attribute(span: Any, key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (str, bool, int, float)):
        span.set_attribute(key, value)
    else:
        span.set_attribute(key, str(value)[:500])
