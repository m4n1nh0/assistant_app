"""Grafo do chat: monta os nos, as arestas e a entrada publica de execucao.

Este e o orquestrador do backend. Cada mensagem entra no grafo e sai por uma de
cinco rotas: propor uma **acao** local (computador, codigo, projeto, atalho,
evento, educacao), responder uma **consulta de agenda**, ou gerar resposta em
modo `single`, `multi` ou `chain`.

O que este arquivo faz e so composicao. A logica de cada passo mora em
`nodes/`, a decisao de rota em `routing.py`, o formato do estado em `state.py` e
a persistencia em `checkpoint.py`. Os colaboradores externos - busca semantica,
subgrafo de agente, despacho a provedores - entram por injecao, entao o grafo
nao importa nenhuma implementacao concreta.
"""

from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from loguru import logger

from ..core.config import get_settings
from ..core.observability import bind, current_context, new_id, span
from ..models.schemas import LLMResponse, Message, ResponseModeEnum
from .checkpoint import build_checkpointer, thread_config
from .nodes.action_detection import detect_action, resolve_shortcut
from .nodes.dispatch import (
    build_dispatch_chain,
    build_dispatch_multi,
    build_dispatch_single,
)
from .nodes.responses import acknowledge_action, query_calendar
from .nodes.retrieval import build_retrieve_context
from .routing import route_after_resolution
from .state import ChatGraphState, ChatRuntimeContext

settings = get_settings()


def build_chat_graph(
    *,
    retrieval=None,
    run_agents=None,
    dispatch_multi=None,
    dispatch_chain=None,
    checkpointer: Any = None,
    node_max_attempts: int = 1,
):
    """Compila o grafo do chat.

    Args:
        retrieval: gateway de busca semantica; `None` resolve o do processo na
            hora da chamada.
        run_agents: executor do subgrafo de agente; `None` usa o padrao.
        dispatch_multi: despacho paralelo a varios provedores.
        dispatch_chain: despacho encadeado entre provedores.
        checkpointer: persistencia do estado; `None` desliga a retomada.
        node_max_attempts: tentativas por no, aplicadas pelo LangGraph nos
            passos que dependem de servico externo.

    Returns:
        O grafo compilado.
    """
    # Colaborador nao informado fica `None` de proposito: cada no resolve o
    # padrao na hora da chamada. Como este grafo e compilado no import do
    # modulo, amarrar as implementacoes aqui as congelaria para o processo
    # inteiro - e nao daria para trocar nem em teste nem em outra composicao.
    external = RetryPolicy(max_attempts=max(1, node_max_attempts))

    workflow = StateGraph(ChatGraphState, context_schema=ChatRuntimeContext)
    workflow.add_node("detect_action", detect_action, retry_policy=external)
    workflow.add_node("resolve_shortcut", resolve_shortcut)
    workflow.add_node(
        "retrieve_context",
        build_retrieve_context(retrieval),
        retry_policy=external,
    )
    workflow.add_node("acknowledge_action", acknowledge_action)
    workflow.add_node("query_calendar", query_calendar)
    workflow.add_node("dispatch_single", build_dispatch_single(run_agents))
    workflow.add_node("dispatch_multi", build_dispatch_multi(dispatch_multi))
    workflow.add_node("dispatch_chain", build_dispatch_chain(dispatch_chain))

    workflow.add_edge(START, "detect_action")
    workflow.add_edge("detect_action", "resolve_shortcut")
    workflow.add_edge("resolve_shortcut", "retrieve_context")
    workflow.add_conditional_edges(
        "retrieve_context",
        route_after_resolution,
        {
            "action": "acknowledge_action",
            "calendar_query": "query_calendar",
            "single": "dispatch_single",
            "multi": "dispatch_multi",
            "chain": "dispatch_chain",
        },
    )
    workflow.add_edge("acknowledge_action", END)
    workflow.add_edge("query_calendar", END)
    workflow.add_edge("dispatch_single", END)
    workflow.add_edge("dispatch_multi", END)
    workflow.add_edge("dispatch_chain", END)
    return workflow.compile(checkpointer=checkpointer)


chat_checkpointer = build_checkpointer(
    settings.checkpoint_backend,
    sqlite_path=settings.checkpoint_sqlite_path,
    max_threads=settings.checkpoint_max_threads,
)
chat_graph = build_chat_graph(
    checkpointer=chat_checkpointer,
    node_max_attempts=max(1, settings.graph_node_max_retries),
)


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
    """Roda o grafo para uma mensagem e devolve o estado final.

    Args:
        message: pergunta do usuario.
        history: historico da conversa.
        mode: `single`, `multi` ou `chain`.
        requested_llm: provedor pedido explicitamente; `None` deixa o roteamento
            decidir.
        active_llms: provedores disponiveis nesta requisicao.
        system_prompt: instrucao de sistema com persona e contexto.
        tutor_id: perfil de dados dono da conversa.
        user_id: conta autenticada.
        timezone: fuso do usuario, usado nas datas.
        conversation_id: sessao de chat; e o `thread_id` do checkpoint e o que
            permite retomar a execucao no lugar de refaze-la.
        execution_id: identificador desta passagem; gerado quando ausente.

    Returns:
        O estado final, com as respostas geradas ou a acao proposta a interface.
    """
    execution = execution_id or new_id()
    context = ChatRuntimeContext(
        requested_llm=requested_llm,
        active_llms=tuple(active_llms),
        tutor_id=tutor_id,
        user_id=user_id,
        timezone=timezone,
        conversation_id=conversation_id,
        execution_id=execution,
    )

    with bind(
        conversation_id=conversation_id,
        execution_id=execution,
        tenant_id=tutor_id,
        user_id=user_id,
    ):
        try:
            async with span(
                "graph.chat", "graph", mode=mode.value, provider=requested_llm
            ) as observed:
                result = await chat_graph.ainvoke(
                    {
                        "message": message,
                        "history": history,
                        "mode": mode,
                        "system_prompt": system_prompt,
                        "execution_id": execution,
                        # Mensagem nova comeca sem acao. O checkpoint e indexado
                        # pela conversa, entao sem zerar aqui a acao da rodada
                        # anterior sobrevivia no estado e voltava na resposta -
                        # a interface executava de novo o mesmo diagnostico, e o
                        # resultado disso virava outra rodada, em loop.
                        "action": None,
                        "action_kind": "unresolved",
                        "tool_trace": [],
                        "handoffs": [],
                        "errors": [],
                    },
                    context=context,
                    config=thread_config(
                        conversation_id=conversation_id or execution,
                        tenant_id=tutor_id,
                        execution_id=execution,
                    ),
                )
                observed.set(
                    action_kind=result.get("action_kind"),
                    agent=result.get("agent_id"),
                )
            return cast(ChatGraphState, result)
        except Exception as exc:
            logger.exception("Chat graph failed: {}", exc)
            return {
                "action_kind": "chat",
                "action": None,
                "execution_id": execution,
                "errors": [str(exc)],
                "responses": [
                    LLMResponse(
                        llm=requested_llm or "backend",
                        content=(
                            "Nao consegui processar sua mensagem agora. "
                            "Tente novamente ou selecione outro agente."
                        ),
                        is_error=True,
                    )
                ],
            }


async def resume_chat_graph(
    *,
    conversation_id: str,
    tutor_id: str = "",
    resume_value: Any = None,
) -> ChatGraphState:
    """Retoma uma execucao interrompida a partir do ultimo checkpoint.

    So faz sentido quando ha checkpointer ligado: sem ele nao existe estado
    gravado para retomar, e a chamada devolve um erro explicito em vez de
    executar do zero, o que reprocessaria uma conversa ja respondida.

    Args:
        conversation_id: sessao cuja execucao ficou pendente.
        tutor_id: dono dos dados, usado no namespace do checkpoint.
        resume_value: valor a devolver a um `interrupt`, quando houver.

    Returns:
        O estado apos a retomada.
    """
    from langgraph.types import Command

    if chat_checkpointer is None:
        return {
            "action_kind": "chat",
            "errors": ["checkpointing desligado: nao ha execucao para retomar"],
            "responses": [
                LLMResponse(
                    llm="backend",
                    content="Retomada indisponivel nesta instalacao.",
                    is_error=True,
                )
            ],
        }

    config = thread_config(conversation_id=conversation_id, tenant_id=tutor_id)
    async with span("graph.resume", "graph", conversation=conversation_id):
        result = await chat_graph.ainvoke(
            Command(resume=resume_value) if resume_value is not None else None,
            config=config,
        )
    return cast(ChatGraphState, result)


async def graph_state(
    *,
    conversation_id: str,
    tutor_id: str = "",
) -> dict[str, Any]:
    """Estado gravado de uma conversa, para diagnostico e retomada.

    Returns:
        O que o checkpointer guarda daquela linha de execucao, ou um aviso de
        que a persistencia esta desligada.
    """
    if chat_checkpointer is None:
        return {"available": False, "reason": "checkpointing desligado"}

    config = thread_config(conversation_id=conversation_id, tenant_id=tutor_id)
    snapshot = await chat_graph.aget_state(config)
    return {
        "available": True,
        "conversation_id": conversation_id,
        "next": list(snapshot.next),
        "action_kind": snapshot.values.get("action_kind"),
        "agent_id": snapshot.values.get("agent_id"),
        "execution_id": snapshot.values.get("execution_id"),
        "errors": snapshot.values.get("errors") or [],
        "checkpoint_id": (snapshot.config or {})
        .get("configurable", {})
        .get("checkpoint_id"),
    }


__all__ = [
    "ChatGraphState",
    "ChatRuntimeContext",
    "build_chat_graph",
    "chat_graph",
    "chat_checkpointer",
    "graph_state",
    "resume_chat_graph",
    "run_chat_graph",
]
