"""Contrato de telemetria: o que a aplicacao emite, sem dizer para onde vai.

A aplicacao registra dois tipos de fato: uma operacao terminou (`SpanRecord`) e
uma chamada de IA consumiu recurso (`UsageRecord`). Quem escuta - log,
OpenTelemetry, agregador em memoria - e decisao de configuracao, nao de dominio.

Essa separacao e o que atende a exigencia de nao acoplar a aplicacao a um
fornecedor de observabilidade: trocar de exporter nao muda uma linha de regra
de negocio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

SpanKind = Literal[
    "http",
    "graph",
    "node",
    "agent",
    "tool",
    "mcp",
    "llm",
    "rag",
    "handoff",
    "external",
]


@dataclass(frozen=True)
class SpanRecord:
    """Uma operacao que comecou, terminou e vale registrar.

    Attributes:
        name: nome da operacao, no formato `dominio.operacao`.
        kind: familia da operacao, usada para filtrar e agregar.
        duration_ms: quanto durou.
        ok: `False` quando terminou em erro.
        error: a mensagem de erro, quando houve.
        attributes: detalhes especificos daquela familia (provedor, tool, nó).
        correlation: os identificadores de `ObservabilityContext` no momento.
        retries: quantas tentativas alem da primeira foram gastas.
    """

    name: str
    kind: SpanKind
    duration_ms: float
    ok: bool = True
    error: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    correlation: dict[str, str] = field(default_factory=dict)
    retries: int = 0


@dataclass(frozen=True)
class UsageRecord:
    """Consumo de uma unica chamada a um modelo.

    Guarda o que o provedor informou, sem inventar o que ele nao mandou:
    `None` significa "o provedor nao devolveu", e nao "zero". A diferenca
    importa na hora de somar custo - tratar ausencia como zero produz relatorio
    que parece barato e esta errado.
    """

    provider: str
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    duration_ms: float = 0.0
    estimated_cost_usd: float | None = None
    agent_id: str = ""
    tool_name: str = ""
    ok: bool = True
    correlation: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class TelemetrySink(Protocol):
    """Destino de telemetria. Implementacoes nunca podem levantar excecao."""

    def record_span(self, span: SpanRecord) -> None:
        """Registra uma operacao concluida."""

    def record_usage(self, usage: UsageRecord) -> None:
        """Registra o consumo de uma chamada de modelo."""
