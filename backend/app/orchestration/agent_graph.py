"""Subgrafo do agente: ciclo modelo -> ferramenta -> modelo e handoff A2A.

Antes isso era um `for hop in range(...)` com um executor de ferramenta escrito
a mao. Agora sao nos e arestas de verdade, com ganhos concretos:

- **`ToolNode` do LangGraph** cuida da mecanica de executar as chamadas,
  inclusive em paralelo, e de devolver `ToolMessage` no formato certo. O que era
  codigo nosso passou a ser o caminho testado do framework.
- **`Command(goto=...)`** expressa a transferencia entre agentes como transicao
  do grafo. O handoff deixou de ser efeito colateral de uma variavel de laco e
  virou aresta observavel.
- **`RetryPolicy`** por no substitui a repeticao manual em volta da chamada.
- **`context_schema`** carrega o que e da requisicao - prompt, provedores,
  tetos - fora do estado. Estado guarda o que decide o fluxo; contexto guarda o
  que a execucao precisa para acontecer.

A governanca de ferramenta continua fora daqui: o `ToolNode` recebe `BaseTool`
que apenas delegam ao Tool Gateway, entao autorizacao, timeout, retry e
auditoria seguem no Tool Service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Awaitable, Callable, Literal, Sequence, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy
from loguru import logger
from pydantic import BaseModel, Field

from ..core.observability import bind, span
from ..models.schemas import LLMResponse
from .agents import HANDOFF_TOOL_NAME, SPECIALISTS, Specialist, handoff_targets


class HandoffInput(BaseModel):
    """Pedido de transferencia feito pelo modelo, ainda por validar."""

    agent: str = Field(description="id do agente que deve assumir")
    reason: str = Field(default="", description="por que a transferencia")


class AgentState(TypedDict, total=False):
    """Estado do subgrafo de um agente.

    Deliberadamente pequeno: so o que decide o proximo passo. `tool_trace` e
    `handoffs` viajam junto porque a interface os exibe, mas nenhuma aresta
    olha para eles - sao saida, nao decisao.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    current_agent: str
    hops: int
    iterations: int
    visited: list[str]
    tool_trace: list[dict[str, Any]]
    handoffs: list[dict[str, str]]
    response: LLMResponse | None


@dataclass
class AgentRuntimeContext:
    """O que vale por requisicao, fora do estado do grafo.

    Attributes:
        system_prompt: instrucao de sistema ja montada com persona e contexto.
        requested_llm: provedor pedido explicitamente pelo usuario.
        active_llms: provedores disponiveis nesta requisicao.
        max_tool_iterations: quantas rodadas de ferramenta sao permitidas.
        max_hops: quantas transferencias entre agentes sao permitidas.
    """

    system_prompt: str = ""
    requested_llm: str | None = None
    active_llms: tuple[str, ...] = ()
    max_tool_iterations: int = 3
    max_hops: int = 2


# Assinaturas dos colaboradores injetados na construcao do grafo. Sao portas:
# o subgrafo nao sabe qual provedor responde nem de onde vem a ferramenta.
CallModel = Callable[
    [AgentState, Specialist, Sequence[BaseTool], AgentRuntimeContext],
    Awaitable[tuple[AIMessage, LLMResponse]],
]
ToolsFor = Callable[[Specialist, bool], Awaitable[list[BaseTool]]]
Finalize = Callable[
    [AgentState, Specialist, AgentRuntimeContext], Awaitable[LLMResponse]
]


def build_handoff_tool(current: str) -> BaseTool:
    """Ferramenta A2A, com a lista de destinos montada em tempo de execucao.

    Ela nao transfere nada: so registra o pedido. Quem valida destino, conta
    saltos e evita que dois agentes devolvam a conversa um ao outro e o no
    `handoff` do grafo. Deixar a decisao na ferramenta daria ao modelo o poder
    de escolher para onde o fluxo vai.
    """
    others = handoff_targets(current)
    catalog = "; ".join(f"{item.id} ({item.description})" for item in others)

    def _transfer(agent: str, reason: str = "") -> str:
        return f"transferencia solicitada para {agent}: {reason}"

    return StructuredTool.from_function(
        func=_transfer,
        name=HANDOFF_TOOL_NAME,
        description=(
            "Transfere a conversa para outro agente quando o pedido nao e da "
            f"sua area. Agentes disponiveis: {catalog}."
        ),
        args_schema=HandoffInput,
    )


def build_agent_graph(
    *,
    call_model: CallModel,
    tools_for: ToolsFor,
    finalize: Finalize,
    node_max_attempts: int = 1,
):
    """Compila o subgrafo de agente.

    Args:
        call_model: fala com o provedor e devolve `(AIMessage, LLMResponse)`.
        tools_for: consulta o Tool Gateway e devolve as tools do especialista.
        finalize: pede a resposta final sem ferramentas quando o teto de
            iteracoes estoura, para o usuario nao receber um JSON de tool call.
        node_max_attempts: tentativas do no de modelo, aplicadas pelo LangGraph.

    Returns:
        O grafo compilado, pronto para `ainvoke` com `context=`.
    """

    async def _agent(
        state: AgentState, runtime: Runtime[AgentRuntimeContext]
    ) -> dict[str, Any]:
        context = runtime.context
        specialist = SPECIALISTS[state["current_agent"]]
        allow_handoff = state.get("hops", 0) < context.max_hops
        tools = await tools_for(specialist, allow_handoff)

        with bind(agent_id=specialist.id):
            async with span(
                f"agent.{specialist.id}",
                "agent",
                agent=specialist.id,
                tools=len(tools),
                hop=state.get("hops", 0),
                iteration=state.get("iterations", 0),
            ) as observed:
                message, response = await call_model(
                    state, specialist, tools, context
                )
                observed.set(
                    provider=response.llm,
                    tool_calls=len(getattr(message, "tool_calls", None) or []),
                )
                if response.is_error:
                    observed.fail(response.content)

        return {
            "messages": [message],
            "response": response,
            "iterations": state.get("iterations", 0) + 1,
        }

    async def _tools(state: AgentState, runtime: Runtime[AgentRuntimeContext]):
        specialist = SPECIALISTS[state["current_agent"]]
        allow_handoff = state.get("hops", 0) < runtime.context.max_hops
        node = ToolNode(await tools_for(specialist, allow_handoff))
        result = await node.ainvoke(state)
        produced = result.get("messages", []) if isinstance(result, dict) else []
        return {
            "messages": produced,
            "tool_trace": list(state.get("tool_trace") or [])
            + _trace_from(state.get("messages") or [], produced),
        }

    async def _handoff(
        state: AgentState, runtime: Runtime[AgentRuntimeContext]
    ) -> Command:
        call = _last_handoff_call(state.get("messages") or [])
        args = dict((call or {}).get("args") or {})
        current = state["current_agent"]
        target_id = str(args.get("agent") or "").strip()
        target = SPECIALISTS.get(target_id)
        visited = list(state.get("visited") or [current])

        trace = list(state.get("tool_trace") or [])
        trace.append(
            {
                "tool": HANDOFF_TOOL_NAME,
                "args": args,
                "output": "",
                "stopped": True,
            }
        )

        # Destino invalido ou ja visitado encerra o repasse: sem isso, dois
        # agentes podem empurrar a conversa um para o outro ate o teto.
        if target is None or target.id in visited:
            logger.info(
                f"Transferencia ignorada ({current} -> {target_id or 'vazio'})"
            )
            return Command(goto=END, update={"tool_trace": trace})

        handoffs = list(state.get("handoffs") or [])
        handoffs.append(
            {
                "from": current,
                "to": target.id,
                "reason": str(args.get("reason") or ""),
            }
        )
        visited.append(target.id)
        return Command(
            goto="agent",
            update={
                "current_agent": target.id,
                "hops": state.get("hops", 0) + 1,
                "iterations": 0,
                "handoffs": handoffs,
                "visited": visited,
                "tool_trace": trace,
                # A conversa recomeca com o novo especialista: a instrucao do
                # anterior sai e a tentativa dele tambem. Arrastar as duas faria
                # o proximo responder ao raciocinio do colega em vez de ao
                # pedido do usuario.
                "messages": _rebuild_for(
                    state.get("messages") or [],
                    runtime.context.system_prompt,
                    target,
                ),
            },
        )

    async def _finalize(
        state: AgentState, runtime: Runtime[AgentRuntimeContext]
    ) -> dict[str, Any]:
        specialist = SPECIALISTS[state["current_agent"]]
        async with span("agent.finalize", "agent", agent=specialist.id):
            response = await finalize(state, specialist, runtime.context)
        return {"response": response}

    workflow = StateGraph(AgentState, context_schema=AgentRuntimeContext)
    workflow.add_node(
        "agent",
        _agent,
        retry_policy=RetryPolicy(max_attempts=max(1, node_max_attempts)),
    )
    workflow.add_node("tools", _tools)
    workflow.add_node("handoff", _handoff)
    workflow.add_node("finalize", _finalize)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "tools": "tools",
            "handoff": "handoff",
            "finalize": "finalize",
            "end": END,
        },
    )
    workflow.add_edge("tools", "agent")
    workflow.add_edge("finalize", END)
    return workflow.compile()


def _route_after_agent(
    state: AgentState, runtime: Runtime[AgentRuntimeContext]
) -> Literal["tools", "handoff", "finalize", "end"]:
    """Decide o proximo passo pela ultima mensagem do modelo.

    A ordem importa: pedido de transferencia ganha da execucao de ferramenta.
    Se a ferramenta rodasse primeiro, o agente errado ja teria agido antes de
    admitir que o pedido nao era dele.
    """
    messages = state.get("messages") or []
    if not messages:
        return "end"
    calls = getattr(messages[-1], "tool_calls", None) or []
    if not calls:
        return "end"
    if any(call.get("name") == HANDOFF_TOOL_NAME for call in calls):
        return "handoff"
    if state.get("iterations", 0) >= max(1, runtime.context.max_tool_iterations):
        # Estourou o teto e o modelo ainda quer ferramenta: fecha pedindo a
        # resposta final sem tools, para nao devolver JSON cru ao usuario.
        return "finalize"
    return "tools"


def _rebuild_for(
    messages: Sequence[BaseMessage],
    base_prompt: str,
    target: Specialist,
) -> list[BaseMessage]:
    """Troca a instrucao de sistema e descarta o que o agente anterior produziu.

    O historico do usuario permanece: o que sai e a instrucao do especialista
    que esta saindo, a resposta parcial dele e os resultados de ferramenta que
    ele pediu.
    """
    from langchain_core.messages import RemoveMessage, SystemMessage, ToolMessage

    updates: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, (AIMessage, ToolMessage, SystemMessage)):
            if message.id:
                updates.append(RemoveMessage(id=message.id))
    updates.append(
        SystemMessage(content="\n\n".join([base_prompt, target.instructions]))
    )
    return updates


def _last_handoff_call(messages: Sequence[BaseMessage]) -> dict[str, Any] | None:
    for message in reversed(list(messages)):
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") == HANDOFF_TOOL_NAME:
                return call
    return None


def _trace_from(
    before: Sequence[BaseMessage],
    produced: Sequence[BaseMessage],
) -> list[dict[str, Any]]:
    """Monta o rastro de ferramentas a partir do que o `ToolNode` devolveu."""
    calls: dict[str, dict[str, Any]] = {}
    for message in before:
        for call in getattr(message, "tool_calls", None) or []:
            calls[str(call.get("id"))] = call

    trace: list[dict[str, Any]] = []
    for message in produced:
        call = calls.get(str(getattr(message, "tool_call_id", "")))
        if call is None:
            continue
        trace.append(
            {
                "tool": call.get("name", ""),
                "args": call.get("args") or {},
                "output": str(getattr(message, "content", ""))[:2000],
            }
        )
    return trace


__all__ = [
    "AgentRuntimeContext",
    "AgentState",
    "HandoffInput",
    "build_agent_graph",
    "build_handoff_tool",
]
