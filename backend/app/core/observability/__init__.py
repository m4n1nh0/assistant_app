"""Observabilidade transversal: correlacao, tracing, custo e destinos.

A regra que organiza este pacote e que **observar e responsabilidade de fora do
dominio**. Agente, no de grafo e regra de negocio abrem span e emitem consumo;
para onde isso vai - log, OpenTelemetry, LangSmith, memoria - e configuracao.

Dois planos convivem de proposito:

- **Aplicacao**: rota HTTP, servico, banco, fila, latencia, erro. Sai em
  `SpanRecord` e vai para OTel.
- **IA**: prompt, chamada de modelo, agente, grafo, tool. Sai tambem em
  `UsageRecord` e pode ir para o LangSmith.

Os dois compartilham o mesmo `trace_id`, entao da para sair de um trace de rota
lenta e cair na chamada de modelo que a deixou lenta.
"""

from .context import (
    ObservabilityContext,
    bind,
    context_from_headers,
    current_context,
    new_id,
    parse_traceparent,
    reset_context,
    set_context,
)
from .costs import build_usage, estimate_cost, load_pricing_overrides, price_for
from .sinks import CompositeSink, InMemorySink, LoggingSink, NullSink
from .tracing import (
    SpanHandle,
    configure_sink,
    default_sink,
    get_sink,
    memory_sink,
    record_usage,
    span,
    span_sync,
)

__all__ = [
    "CompositeSink",
    "InMemorySink",
    "LoggingSink",
    "NullSink",
    "ObservabilityContext",
    "SpanHandle",
    "bind",
    "build_usage",
    "configure_sink",
    "context_from_headers",
    "current_context",
    "default_sink",
    "estimate_cost",
    "get_sink",
    "load_pricing_overrides",
    "memory_sink",
    "new_id",
    "parse_traceparent",
    "price_for",
    "record_usage",
    "reset_context",
    "set_context",
    "span",
    "span_sync",
]
