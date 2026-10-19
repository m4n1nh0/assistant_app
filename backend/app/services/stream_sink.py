"""Canal por onde o modelo do grafo entrega o texto aos pedacos enquanto o turno roda.

Quem quer acompanhar a resposta (a rota de streaming, o orquestrador) amarra um `sink` neste
`ContextVar` antes de rodar o grafo. O `ProviderChatModel` olha aqui: sem `sink`, chama o provedor
inteiro como sempre; com `sink`, usa o streaming e repassa cada pedaco.

Os eventos sao dicionarios simples, para atravessarem a rede sem traducao:

- `{"type": "reset"}`: uma nova chamada ao modelo comecou; o que veio antes deve ser descartado.
  Acontece a cada volta do agente (depois de uma ferramenta, em retentativa, em transferencia).
- `{"type": "delta", "text": "..."}`: mais um pedaco da resposta.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Awaitable, Callable, Optional

Sink = Callable[[dict], Awaitable[None]]

_current: ContextVar[Optional[Sink]] = ContextVar("llm_stream_sink", default=None)


def bind_sink(sink: Sink) -> Token:
    """Liga o canal para o que roda a partir daqui; devolva o token a `reset_sink`."""
    return _current.set(sink)


def reset_sink(token: Token) -> None:
    """Desliga o canal ligado por `bind_sink`."""
    _current.reset(token)


def current_sink() -> Optional[Sink]:
    """O canal ativo neste contexto, ou `None` quando ninguem acompanha o texto."""
    return _current.get()
