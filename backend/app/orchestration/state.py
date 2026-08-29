"""Estado e contexto de execucao do grafo do chat.

A regra que separa os dois e simples e vale a pena repetir: **estado e o que
decide o fluxo; contexto e o que a execucao precisa para acontecer.**

- `ChatGraphState` guarda o que um no le para escolher o proximo passo, mais o
  que a interface consome no fim. Ele e persistido pelo checkpointer, entao
  cada campo aqui e algo que faz sentido reler numa retomada.
- `ChatRuntimeContext` guarda o que vale so para esta requisicao: provedores
  disponiveis, fuso, dono dos dados, identificadores de correlacao. Nada disso
  decide ramificacao, e nada disso deveria ser regravado em checkpoint - alem
  de inflar o estado, provedor disponivel na hora da pausa nao e o mesmo na
  hora da retomada.

Os campos de saida (`tool_trace`, `handoffs`) ficam no estado por um motivo
pratico: a interface os exibe. Nenhuma aresta olha para eles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from ..models.schemas import LLMResponse, Message, ResponseModeEnum

ActionKind = Literal[
    "unresolved",
    "chat",
    "launch",
    "computer",
    "coding",
    "project",
    "registration",
    "calendar",
    "calendar_query",
    "education",
]

GraphRoute = Literal["action", "calendar_query", "single", "multi", "chain"]

# Rotas que ja tem resposta propria e nao passam por modelo nem por RAG.
NON_CHAT_KINDS: frozenset[str] = frozenset({
    "computer",
    "coding",
    "project",
    "registration",
    "calendar",
    "calendar_query",
    "education",
})

# Tipos de acao que a interface confirma e executa.
ACTION_KINDS: frozenset[str] = frozenset({
    "computer",
    "coding",
    "project",
    "registration",
    "calendar",
    "education",
})


class ChatGraphState(TypedDict, total=False):
    """Estado que atravessa o grafo do chat.

    Attributes:
        message: pergunta do usuario.
        history: historico da conversa.
        mode: `single`, `multi` ou `chain`.
        system_prompt: instrucao de sistema, enriquecida pelos nos de contexto.
        action_kind: rota decidida pela deteccao de acao.
        task_kind: tarefa detectada, que escolhe especialista e provedor.
        action: acao proposta a interface, quando houver.
        responses: respostas geradas.
        agent_id: especialista que respondeu.
        tool_trace: rastro de ferramentas usadas, para a interface exibir.
        handoffs: transferencias entre agentes que aconteceram.
        errors: falhas nao fatais acumuladas durante a execucao.
        execution_id: identificador desta passagem pelo grafo.
    """

    message: str
    history: list[Message]
    mode: ResponseModeEnum
    system_prompt: str

    action_kind: ActionKind
    task_kind: str

    action: Any
    responses: list[LLMResponse]

    agent_id: str
    tool_trace: list[dict[str, Any]]
    handoffs: list[dict[str, str]]
    errors: list[str]
    execution_id: str


@dataclass
class ChatRuntimeContext:
    """O que vale por requisicao, fora do estado persistido.

    Attributes:
        requested_llm: provedor pedido explicitamente; `None` deixa o roteador
            decidir e habilita o fallback entre provedores.
        active_llms: provedores disponiveis no momento da requisicao.
        tutor_id: perfil de dados dono da conversa; isola a busca por conta.
        user_id: conta autenticada.
        timezone: fuso do usuario, usado ao interpretar datas.
        conversation_id: sessao de chat, usada como `thread_id` do checkpoint.
        execution_id: identificador desta execucao, usado para idempotencia.
    """

    requested_llm: str | None = None
    active_llms: tuple[str, ...] = ()
    tutor_id: str = ""
    user_id: str = ""
    timezone: str = "America/Sao_Paulo"
    conversation_id: str = ""
    execution_id: str = ""
