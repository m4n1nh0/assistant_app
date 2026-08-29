"""Destinos de telemetria: log, memoria e OpenTelemetry.

Sao intercambiaveis por construcao - quem emite fala com `TelemetrySink` e nao
sabe qual destes esta ligado. `CompositeSink` permite ter os tres ao mesmo
tempo sem que o emissor saiba disso.

Regra que vale para todos: **nenhum sink pode levantar excecao**. Falha ao
observar nao pode derrubar o que estava sendo observado.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Iterable

from loguru import logger

from ...ports.telemetry import SpanRecord, TelemetrySink, UsageRecord


class NullSink:
    """Descarta tudo. Padrao quando a observabilidade esta desligada."""

    def record_span(self, span: SpanRecord) -> None:
        return None

    def record_usage(self, usage: UsageRecord) -> None:
        return None


class LoggingSink:
    """Escreve no loguru, com os identificadores de correlacao na linha.

    E o destino de fallback: sem collector configurado, ainda da para reconstruir
    uma execucao pelo arquivo de log filtrando por `execution_id`.
    """

    def __init__(self, *, slow_ms: float = 1500.0) -> None:
        self._slow_ms = slow_ms

    @staticmethod
    def _prefix(correlation: dict[str, str]) -> str:
        keys = ("request_id", "execution_id", "agent_id")
        parts = [f"{key}={correlation[key]}" for key in keys if correlation.get(key)]
        return " ".join(parts)

    def record_span(self, span: SpanRecord) -> None:
        try:
            prefix = self._prefix(span.correlation)
            line = (
                f"[{span.kind}] {span.name} {span.duration_ms:.1f}ms "
                f"{'ok' if span.ok else 'erro'} {prefix}"
            ).strip()
            if not span.ok:
                logger.warning(f"{line} | {span.error}")
            elif span.duration_ms >= self._slow_ms:
                logger.info(line)
            else:
                logger.debug(line)
        except Exception:
            pass

    def record_usage(self, usage: UsageRecord) -> None:
        try:
            cost = (
                f"~${usage.estimated_cost_usd:.6f}"
                if usage.estimated_cost_usd is not None
                else "custo desconhecido"
            )
            logger.debug(
                f"[llm] {usage.provider}/{usage.model or '?'} "
                f"in={usage.input_tokens} out={usage.output_tokens} {cost} "
                f"{self._prefix(usage.correlation)}".strip()
            )
        except Exception:
            pass


class InMemorySink:
    """Guarda os ultimos eventos para o endpoint de diagnostico.

    Janela limitada de proposito: o backend roda por dias na maquina do usuario
    e um historico ilimitado viraria vazamento de memoria. Para retencao longa,
    o caminho e o exporter OTLP, nao este buffer.
    """

    def __init__(self, *, max_events: int = 2000) -> None:
        self._spans: deque[SpanRecord] = deque(maxlen=max_events)
        self._usage: deque[UsageRecord] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def record_span(self, span: SpanRecord) -> None:
        try:
            with self._lock:
                self._spans.append(span)
        except Exception:
            pass

    def record_usage(self, usage: UsageRecord) -> None:
        try:
            with self._lock:
                self._usage.append(usage)
        except Exception:
            pass

    def spans(self) -> list[SpanRecord]:
        """Copia dos spans na janela atual."""
        with self._lock:
            return list(self._spans)

    def usage(self) -> list[UsageRecord]:
        """Copia dos registros de consumo na janela atual."""
        with self._lock:
            return list(self._usage)

    def clear(self) -> None:
        """Descarta a janela. Usado nos testes e no endpoint de reset."""
        with self._lock:
            self._spans.clear()
            self._usage.clear()

    def summarize(self, *, group_by: str = "provider") -> dict[str, Any]:
        """Agrega o consumo da janela por uma dimensao.

        Args:
            group_by: `provider`, `model`, `agent_id`, `tool_name`,
                `conversation_id`, `request_id` ou `execution_id`. As tres
                ultimas saem da correlacao.

        Returns:
            Totais gerais e por grupo, com tokens, custo estimado e contagem.
        """
        correlation_keys = {"conversation_id", "request_id", "execution_id"}
        groups: dict[str, dict[str, Any]] = {}
        totals = _empty_bucket()

        for record in self.usage():
            key = (
                record.correlation.get(group_by, "")
                if group_by in correlation_keys
                else str(getattr(record, group_by, ""))
            ) or "desconhecido"
            bucket = groups.setdefault(key, _empty_bucket())
            for target in (bucket, totals):
                _accumulate(target, record)

        return {
            "group_by": group_by,
            "totals": totals,
            "groups": dict(
                sorted(
                    groups.items(),
                    key=lambda item: item[1]["estimated_cost_usd"],
                    reverse=True,
                )
            ),
        }


def _empty_bucket() -> dict[str, Any]:
    return {
        "calls": 0,
        "errors": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "duration_ms": 0.0,
        "estimated_cost_usd": 0.0,
        "priced_calls": 0,
    }


def _accumulate(bucket: dict[str, Any], record: UsageRecord) -> None:
    bucket["calls"] += 1
    if not record.ok:
        bucket["errors"] += 1
    bucket["input_tokens"] += record.input_tokens or 0
    bucket["output_tokens"] += record.output_tokens or 0
    bucket["cached_tokens"] += record.cached_tokens or 0
    bucket["total_tokens"] += record.total_tokens or 0
    bucket["duration_ms"] = round(bucket["duration_ms"] + record.duration_ms, 2)
    if record.estimated_cost_usd is not None:
        bucket["estimated_cost_usd"] = round(
            bucket["estimated_cost_usd"] + record.estimated_cost_usd, 8
        )
        bucket["priced_calls"] += 1


class CompositeSink:
    """Reparte os eventos entre varios destinos, isolando falha de cada um."""

    def __init__(self, sinks: Iterable[TelemetrySink]) -> None:
        self._sinks = list(sinks)

    def record_span(self, span: SpanRecord) -> None:
        for sink in self._sinks:
            try:
                sink.record_span(span)
            except Exception:
                pass

    def record_usage(self, usage: UsageRecord) -> None:
        for sink in self._sinks:
            try:
                sink.record_usage(usage)
            except Exception:
                pass
