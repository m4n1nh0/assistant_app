"""API de tracing que a aplicacao usa, independente de quem coleta.

Todo lugar do codigo abre span com `span(...)` ou `span_sync(...)` e nunca fala
com o OpenTelemetry diretamente. Isso deixa duas coisas verdadeiras ao mesmo
tempo: existe tracing distribuido de verdade quando o SDK esta instalado, e o
backend continua subindo e funcionando quando ele nao esta.

O span sempre gera um `SpanRecord` para o sink configurado, mesmo sem OTel -
por isso o log estruturado nao depende do collector estar de pe.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

from ...ports.telemetry import SpanKind, SpanRecord, TelemetrySink, UsageRecord
from .context import current_context
from .sinks import CompositeSink, InMemorySink, LoggingSink, NullSink

_sink: TelemetrySink = NullSink()
_memory: InMemorySink | None = None


def configure_sink(sink: TelemetrySink, *, memory: InMemorySink | None = None) -> None:
    """Define o destino dos eventos. Chamado uma vez, na subida do processo."""
    global _sink, _memory
    _sink = sink
    _memory = memory


def default_sink(*, memory_events: int = 2000) -> tuple[TelemetrySink, InMemorySink]:
    """Monta o destino padrao: log mais janela em memoria para diagnostico."""
    memory = InMemorySink(max_events=memory_events)
    return CompositeSink([LoggingSink(), memory]), memory


def get_sink() -> TelemetrySink:
    """O destino ativo."""
    return _sink


def memory_sink() -> InMemorySink | None:
    """A janela em memoria, quando ela faz parte do destino ativo."""
    return _memory


def record_usage(usage: UsageRecord) -> None:
    """Registra o consumo de uma chamada de modelo no destino ativo."""
    try:
        _sink.record_usage(usage)
    except Exception:
        pass


@dataclass
class SpanHandle:
    """Controle do span aberto: atributos, erro e tentativas."""

    name: str
    kind: SpanKind
    attributes: dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    _error: str = ""
    _ok: bool = True

    def set(self, **attributes: Any) -> None:
        """Acrescenta atributos descobertos durante a operacao."""
        self.attributes.update(
            {key: value for key, value in attributes.items() if value is not None}
        )

    def fail(self, error: object) -> None:
        """Marca o span como erro sem propagar excecao.

        Usado no caminho em que a falha ja virou resposta degradada - o usuario
        recebe uma resposta, mas o trace precisa registrar que houve falha.
        """
        self._ok = False
        self._error = str(error)[:500]

    def retry(self) -> None:
        """Conta mais uma tentativa gasta nesta operacao."""
        self.retries += 1

    @property
    def ok(self) -> bool:
        """Se a operacao terminou sem erro."""
        return self._ok

    def _finish(self, duration_ms: float) -> SpanRecord:
        return SpanRecord(
            name=self.name,
            kind=self.kind,
            duration_ms=round(duration_ms, 3),
            ok=self._ok,
            error=self._error,
            attributes=dict(self.attributes),
            correlation=current_context().as_dict(),
            retries=self.retries,
        )


def _otel_span(name: str, kind: SpanKind, attributes: dict[str, Any]):
    """Abre o span do OpenTelemetry quando o SDK esta presente.

    Devolve um context manager sempre - `nullcontext` quando o SDK nao existe -
    para o chamador nao precisar do `if` em toda chamada.
    """
    from contextlib import nullcontext

    from .otel import start_span

    started = start_span(name, kind, attributes)
    return started if started is not None else nullcontext()


@asynccontextmanager
async def span(
    name: str,
    kind: SpanKind = "external",
    **attributes: Any,
) -> AsyncIterator[SpanHandle]:
    """Mede uma operacao assincrona e registra o resultado.

    Excecao que sobe marca o span como erro e continua subindo: observar nao
    pode mudar o fluxo de controle.

    Args:
        name: nome da operacao, no formato `dominio.operacao`.
        kind: familia da operacao.
        **attributes: atributos ja conhecidos na abertura.

    Yields:
        O `SpanHandle` para enriquecer o span durante a execucao.
    """
    handle = SpanHandle(name=name, kind=kind, attributes=dict(attributes))
    started = time.perf_counter()
    with _otel_span(name, kind, handle.attributes) as otel:
        try:
            yield handle
        except Exception as exc:
            handle.fail(exc)
            raise
        finally:
            record = handle._finish((time.perf_counter() - started) * 1000)
            _emit(record, otel)


@contextmanager
def span_sync(
    name: str,
    kind: SpanKind = "external",
    **attributes: Any,
) -> Iterator[SpanHandle]:
    """Versao sincrona de `span`, para codigo que ainda nao e async."""
    handle = SpanHandle(name=name, kind=kind, attributes=dict(attributes))
    started = time.perf_counter()
    with _otel_span(name, kind, handle.attributes) as otel:
        try:
            yield handle
        except Exception as exc:
            handle.fail(exc)
            raise
        finally:
            record = handle._finish((time.perf_counter() - started) * 1000)
            _emit(record, otel)


def _emit(record: SpanRecord, otel: Any) -> None:
    try:
        _sink.record_span(record)
    except Exception:
        pass
    if otel is None:
        return
    try:
        from .otel import finish_span

        finish_span(otel, record)
    except Exception:
        pass
