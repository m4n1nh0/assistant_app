"""Identificadores de correlacao que atravessam toda a execucao.

Uma pergunta do usuario passa por API, orquestrador, agente, no do grafo, tool,
MCP e provedor. Sem um identificador comum, cada camada registra um pedaco solto
e ninguem consegue remontar o que aconteceu numa conversa especifica.

Os identificadores vivem em `ContextVar`, entao acompanham a corrotina sem
precisar ser passados de funcao em funcao nem entrar no estado do grafo - o
estado do LangGraph guarda o que decide o fluxo, nao o que so serve para
observar. Quando a chamada sai do processo (tool-service, mcp-service), o
contexto viaja em cabecalho HTTP via `traceparent` e `X-Request-ID`.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Iterator

# Cabecalhos usados para propagar o contexto entre servicos. `traceparent` segue
# o formato W3C Trace Context, o mesmo que o OpenTelemetry entende, para que um
# collector consiga costurar os spans sem traducao.
REQUEST_ID_HEADER = "X-Request-ID"
CONVERSATION_ID_HEADER = "X-Conversation-ID"
EXECUTION_ID_HEADER = "X-Execution-ID"
TRACEPARENT_HEADER = "traceparent"

_TRACE_FLAGS_SAMPLED = "01"
_TRACEPARENT_VERSION = "00"


def new_id() -> str:
    """Identificador curto e unico, no formato usado por todos os IDs daqui."""
    return uuid.uuid4().hex


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class ObservabilityContext:
    """Os identificadores de uma execucao em andamento.

    Attributes:
        request_id: uma requisicao HTTP ou mensagem WebSocket.
        trace_id: o trace distribuido (32 hex), compartilhado entre servicos.
        span_id: o span atual (16 hex), pai dos spans criados a seguir.
        conversation_id: a sessao de chat, estavel entre varias mensagens.
        execution_id: uma passagem pelo grafo; e a chave de idempotencia.
        agent_id: o especialista que esta atendendo no momento.
        tenant_id: o perfil de dados dono da conversa (`tutor_id`).
        user_id: a conta autenticada.
    """

    request_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    conversation_id: str = ""
    execution_id: str = ""
    agent_id: str = ""
    tenant_id: str = ""
    user_id: str = ""

    def traceparent(self) -> str:
        """Serializa o contexto no cabecalho W3C Trace Context."""
        if not self.trace_id:
            return ""
        span = self.span_id or _new_span_id()
        return f"{_TRACEPARENT_VERSION}-{self.trace_id}-{span}-{_TRACE_FLAGS_SAMPLED}"

    def headers(self) -> dict[str, str]:
        """Cabecalhos que levam este contexto para outro servico."""
        out: dict[str, str] = {}
        if self.request_id:
            out[REQUEST_ID_HEADER] = self.request_id
        if self.conversation_id:
            out[CONVERSATION_ID_HEADER] = self.conversation_id
        if self.execution_id:
            out[EXECUTION_ID_HEADER] = self.execution_id
        traceparent = self.traceparent()
        if traceparent:
            out[TRACEPARENT_HEADER] = traceparent
        return out

    def as_dict(self) -> dict[str, str]:
        """Versao plana, para anexar como atributo de span ou campo de log."""
        return {
            key: value
            for key, value in {
                "request_id": self.request_id,
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "conversation_id": self.conversation_id,
                "execution_id": self.execution_id,
                "agent_id": self.agent_id,
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
            }.items()
            if value
        }


_EMPTY = ObservabilityContext()
_current: ContextVar[ObservabilityContext] = ContextVar(
    "observability_context", default=_EMPTY
)


def parse_traceparent(value: str) -> tuple[str, str]:
    """Le `traceparent` recebido de outro servico.

    Args:
        value: conteudo cru do cabecalho.

    Returns:
        `(trace_id, span_id)`, ou `("", "")` quando o cabecalho e invalido. Um
        cabecalho malformado nunca derruba a requisicao: geramos um trace novo,
        que e melhor do que recusar o pedido por causa de telemetria.
    """
    parts = (value or "").strip().split("-")
    if len(parts) < 4:
        return "", ""
    _, trace_id, span_id, *_ = parts
    if len(trace_id) != 32 or len(span_id) != 16:
        return "", ""
    try:
        int(trace_id, 16)
        int(span_id, 16)
    except ValueError:
        return "", ""
    return trace_id, span_id


def context_from_headers(
    headers: dict[str, str] | None = None,
    **overrides: str,
) -> ObservabilityContext:
    """Monta o contexto a partir dos cabecalhos recebidos, completando o que falta.

    Args:
        headers: cabecalhos da requisicao (a leitura ignora maiusculas).
        **overrides: campos conhecidos pela rota, como `tenant_id` e `user_id`.

    Returns:
        Um contexto pronto para `bind`, com trace novo quando o chamador nao
        enviou um.
    """
    lookup = {key.lower(): value for key, value in (headers or {}).items()}
    trace_id, span_id = parse_traceparent(lookup.get(TRACEPARENT_HEADER, ""))
    return ObservabilityContext(
        request_id=lookup.get(REQUEST_ID_HEADER.lower()) or new_id(),
        trace_id=trace_id or new_id(),
        span_id=span_id or _new_span_id(),
        conversation_id=lookup.get(CONVERSATION_ID_HEADER.lower(), ""),
        execution_id=lookup.get(EXECUTION_ID_HEADER.lower(), ""),
        **overrides,
    )


def current_context() -> ObservabilityContext:
    """O contexto ativo nesta corrotina."""
    return _current.get()


def set_context(context: ObservabilityContext) -> Token:
    """Ativa um contexto e devolve o token de restauracao."""
    return _current.set(context)


def reset_context(token: Token) -> None:
    """Restaura o contexto anterior a `set_context`."""
    _current.reset(token)


@contextmanager
def bind(**fields: str) -> Iterator[ObservabilityContext]:
    """Acrescenta campos ao contexto ativo enquanto durar o bloco.

    Campos vazios sao ignorados, entao `bind(agent_id="")` nao apaga o agente
    que ja estava no contexto.

    Args:
        **fields: campos de `ObservabilityContext` a sobrescrever.

    Yields:
        O contexto resultante.
    """
    clean = {key: value for key, value in fields.items() if value}
    context = replace(_current.get(), **clean) if clean else _current.get()
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)
