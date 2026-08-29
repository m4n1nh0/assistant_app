"""Fachada do grafo do chat para a camada de rotas.

O grafo propriamente dito mudou de casa: estado, nos, arestas, roteamento e
checkpoint agora moram em `app.orchestration`, onde cada peca tem arquivo
proprio e pode ser testada sozinha. Este modulo continua sendo o ponto de
entrada que routers e testes conhecem.

Manter a fachada nao e apego ao nome antigo: e o que permitiu migrar a
orquestracao sem mexer em `routers/chat.py`, `routers/websocket.py` nem no
contrato consumido pela interface Flutter.
"""

from __future__ import annotations

from ..orchestration.graph import (
    build_chat_graph,
    chat_checkpointer,
    chat_graph,
    graph_state,
    resume_chat_graph,
    run_chat_graph,
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
