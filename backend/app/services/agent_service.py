"""Execucao dos especialistas e transferencia entre agentes (A2A).

O que este modulo faz mudou de natureza. Antes ele *era* a orquestracao: um laco
que chamava o modelo, executava ferramenta, detectava handoff e repetia. Agora
ele e a **camada de aplicacao** entre o resto do backend e o subgrafo de agente
do LangGraph:

- monta o contexto da requisicao (`AgentRuntimeContext`);
- resolve as ferramentas pelo Tool Gateway, sem saber se elas sao locais ou
  vieram de MCP;
- escolhe o provedor com fallback;
- roda o subgrafo e traduz o estado final para `AgentOutcome`.

Quem controla ciclo, ramificacao e transferencia e o grafo, nao este arquivo.
A definicao dos especialistas mora em `app.orchestration.agents`, sem dependencia
de framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from loguru import logger

from ..adapters.container import get_tool_gateway
from ..adapters.tools.langchain_binding import to_langchain_tools
from ..core.config import get_settings
from ..core.observability import span
from ..models.schemas import LLMResponse, Message
from ..orchestration.agent_graph import (
    AgentRuntimeContext,
    AgentState,
    build_agent_graph,
    build_handoff_tool,
)
from ..orchestration.agents import (
    DEFAULT_SPECIALIST,
    HANDOFF_TOOL_NAME,
    SPECIALISTS,
    Specialist,
    select_specialist,
)
from ..ports.tools import ToolGateway
from . import langchain_agent_service
from .llm_routing_service import rank_auto_llms

settings = get_settings()

__all__ = [
    "AgentOutcome",
    "DEFAULT_SPECIALIST",
    "HANDOFF_TOOL_NAME",
    "SPECIALISTS",
    "Specialist",
    "build_tools",
    "run_agents",
    "select_specialist",
]


@dataclass
class AgentOutcome:
    """Resultado de uma rodada de agentes: resposta, rastro e transferencias feitas."""

    response: LLMResponse
    agent_id: str
    provider: str
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    handoffs: list[dict[str, str]] = field(default_factory=list)


async def build_tools(
    specialist: Specialist,
    *,
    allow_handoff: bool,
    gateway: ToolGateway | None = None,
) -> list[BaseTool]:
    """Monta as ferramentas disponiveis para um especialista.

    O especialista nao escolhe mais o que existe: ele pergunta ao Tool Gateway
    o que **ele** pode usar, e o gateway responde com o catalogo ja filtrado por
    escopo, incluindo as capacidades publicadas via MCP. E por isso que o agente
    nao importa nada de MCP.

    Args:
        specialist: quem vai atender.
        allow_handoff: se ainda ha salto disponivel para transferir a conversa.
        gateway: porta de acesso ao catalogo; `None` usa a do processo.

    Returns:
        As tools no formato que o `ToolNode` do LangGraph executa.
    """
    resolved = gateway if gateway is not None else get_tool_gateway()
    try:
        descriptors = await resolved.list_tools(agent_id=specialist.id)
    except Exception as exc:
        # Catalogo fora do ar nao pode calar o assistente: ele responde sem
        # ferramenta, como ja fazia quando o MCP caia.
        logger.warning(f"Catalogo de ferramentas indisponivel: {exc}")
        descriptors = []

    tools = to_langchain_tools(resolved, descriptors, agent_id=specialist.id)
    if allow_handoff:
        tools.append(build_handoff_tool(specialist.id))
    return tools


async def _providers_for(
    specialist: Specialist,
    context: AgentRuntimeContext,
) -> list[str]:
    if context.requested_llm:
        return [context.requested_llm]
    return await rank_auto_llms(
        list(context.active_llms),
        specialist.routing_task,
        available_only=True,
    )


async def _call_model(
    state: AgentState,
    specialist: Specialist,
    tools: Sequence[BaseTool],
    context: AgentRuntimeContext,
) -> tuple[AIMessage, LLMResponse]:
    """Fala com o provedor, caindo para o proximo quando o primeiro falha.

    O fallback so vale quando o usuario nao pediu um provedor especifico: se ele
    escolheu um agente na interface, trocar por outro pelas costas esconderia a
    indisponibilidade em vez de mostra-la.
    """
    providers = await _providers_for(specialist, context)
    if not providers:
        return (
            AIMessage(content=""),
            LLMResponse(
                llm="backend",
                content="Nenhum agente de IA esta disponivel agora.",
                is_error=True,
            ),
        )

    message = AIMessage(content="")
    response = LLMResponse(llm="backend", content="", is_error=True)
    messages = list(state.get("messages") or [])

    for provider in providers:
        message, response = await langchain_agent_service.invoke_model(
            provider, messages, tools
        )
        if not response.is_error or context.requested_llm:
            break
        logger.warning(
            "Agente {}: {} falhou; tentando proximo provedor disponivel",
            specialist.id,
            provider,
        )
    return message, response


async def _finalize(
    state: AgentState,
    specialist: Specialist,
    context: AgentRuntimeContext,
) -> LLMResponse:
    """Fecha a rodada sem ferramentas quando o teto de iteracoes estoura."""
    providers = await _providers_for(specialist, context)
    if not providers:
        return LLMResponse(
            llm="backend",
            content="Nenhum agente de IA esta disponivel agora.",
            is_error=True,
        )
    return await langchain_agent_service.plain_response(
        providers[0], list(state.get("messages") or [])
    )


async def _tools_for(specialist: Specialist, allow_handoff: bool) -> list[BaseTool]:
    return await build_tools(specialist, allow_handoff=allow_handoff)


def _build_graph():
    return build_agent_graph(
        call_model=_call_model,
        tools_for=_tools_for,
        finalize=_finalize,
        node_max_attempts=1,
    )


agent_graph = _build_graph()
"""Subgrafo compilado do agente, exposto para inspecao e teste."""


async def run_agents(
    *,
    message: str,
    history: list[Message],
    system_prompt: str,
    task: str,
    active_llms: list[str],
    requested_llm: str | None = None,
) -> AgentOutcome:
    """Roda o especialista escolhido, seguindo transferencias ate o teto.

    Args:
        message: pergunta do usuario.
        history: historico da conversa.
        system_prompt: instrucao de sistema com persona e contexto.
        task: tarefa detectada, que escolhe o especialista de entrada.
        active_llms: provedores disponiveis nesta requisicao.
        requested_llm: provedor pedido explicitamente; `None` deixa o roteamento
            decidir e habilita o fallback.

    Returns:
        A resposta final, o agente que respondeu e o rastro de ferramentas e
        transferencias, para a interface poder mostrar o que aconteceu.
    """
    specialist = select_specialist(task)
    context = AgentRuntimeContext(
        system_prompt=system_prompt,
        requested_llm=requested_llm,
        active_llms=tuple(active_llms),
        max_tool_iterations=max(1, settings.agent_max_tool_iterations),
        max_hops=max(0, settings.agent_max_handoffs),
    )

    seed: AgentState = {
        "messages": langchain_agent_service.langchain_messages(
            message, history, f"{system_prompt}\n\n{specialist.instructions}"
        ),
        "current_agent": specialist.id,
        "hops": 0,
        "iterations": 0,
        "visited": [specialist.id],
        "tool_trace": [],
        "handoffs": [],
    }

    async with span("orchestration.agents", "agent", entry_agent=specialist.id):
        final = await agent_graph.ainvoke(seed, context=context)

    response = final.get("response") or LLMResponse(
        llm="backend",
        content="Nao consegui gerar uma resposta agora.",
        is_error=True,
    )
    return AgentOutcome(
        response=response,
        agent_id=str(final.get("current_agent") or specialist.id),
        provider=response.llm if not response.is_error else (requested_llm or ""),
        tool_trace=list(final.get("tool_trace") or []),
        handoffs=list(final.get("handoffs") or []),
    )
