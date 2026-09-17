"""Fachada do grafo do chat para a camada de rotas.

O grafo propriamente dito mudou de casa: estado, nos, arestas, roteamento e
checkpoint agora moram em `app.orchestration`, onde cada peca tem arquivo
proprio e pode ser testada sozinha. Este modulo continua sendo o ponto de
entrada que routers e testes conhecem.

Manter a fachada nao e apego ao nome antigo: e o que permitiu migrar a
orquestracao sem mexer em `routers/chat.py`, `routers/websocket.py` nem no
contrato consumido pela interface Flutter.

`run_chat_graph` daqui nao chama o grafo diretamente: entrega o turno ao
`OrchestrationGateway`, que roda o grafo neste processo ou no agent-orchestrator
conforme `ORCHESTRATOR_TRANSPORT`. O orquestrador, por sua vez, importa o grafo
de `app.orchestration.graph` - nunca desta fachada, senao mandaria o turno para
si mesmo.
"""

from __future__ import annotations

from ..models.schemas import Message, ResponseModeEnum
from ..orchestration.graph import (
    build_chat_graph,
    chat_checkpointer,
    chat_graph,
    graph_state,
    resume_chat_graph,
)
from ..orchestration.nodes.action_detection import (
    is_context_wrapped as _is_context_wrapped,
    lookup_shortcut as _lookup_shortcut,
)
from ..orchestration.nodes.responses import (
    calendar_proposal_text as _calendar_proposal_text,
)
from ..orchestration.routing import route_after_resolution as _route_after_resolution
from ..orchestration.state import (
    ActionKind,
    ChatGraphState,
    ChatRuntimeContext,
    GraphRoute,
)
from . import agent_service, langchain_agent_service


async def run_chat_graph(
    *,
    message: str,
    history: list[Message],
    mode: ResponseModeEnum,
    requested_llm: str | None,
    active_llms: list[str],
    system_prompt: str,
    tutor_id: str,
    user_id: str = "",
    timezone: str = "America/Sao_Paulo",
    conversation_id: str = "",
    execution_id: str = "",
) -> ChatGraphState:
    """Entrega um turno do chat a quem roda o grafo e devolve o estado final.

    Mesma assinatura do grafo, para as rotas nao saberem do transporte. A
    maquina da sessao sai do `ContextVar` que a rota ja amarrou.
    """
    from ..adapters.container import get_orchestration_gateway
    from ..ports.orchestration import ChatTurn
    from .device_catalog_service import current_device

    turn = ChatTurn(
        message=message,
        history=list(history),
        mode=mode,
        requested_llm=requested_llm,
        active_llms=tuple(active_llms),
        system_prompt=system_prompt,
        tutor_id=tutor_id,
        user_id=user_id,
        timezone=timezone,
        conversation_id=conversation_id,
        execution_id=execution_id,
        device_id=current_device(),
    )
    return await get_orchestration_gateway().run_chat(turn)


__all__ = [
    "ActionKind",
    "ChatGraphState",
    "ChatRuntimeContext",
    "GraphRoute",
    "agent_service",
    "build_chat_graph",
    "chat_checkpointer",
    "chat_graph",
    "graph_state",
    "langchain_agent_service",
    "resume_chat_graph",
    "run_chat_graph",
]
