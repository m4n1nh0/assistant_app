"""Ligacao opcional com o OpenTelemetry.

Todo o modulo e defensivo de proposito: o pacote `opentelemetry-sdk` nao e
obrigatorio para rodar o backend. Sem ele, `start_span` devolve `None` e a
abstracao de tracing segue funcionando so com log e memoria.

A escolha do exporter e do endpoint fica no ambiente (`OTEL_EXPORTER_OTLP_*`),
que e o padrao da propria especificacao - nao ha nome de fornecedor no codigo.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from ...ports.telemetry import SpanKind, SpanRecord

_tracer: Any = None
_enabled = False

_KIND_TO_ATTRIBUTE = "assistant.span.kind"


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
                OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
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
