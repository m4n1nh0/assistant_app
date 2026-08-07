"""Especialistas e transferencia entre agentes (A2A).

Cada especialista e um papel com instrucoes proprias e um conjunto de
ferramentas. O roteador escolhe quem atende; o proprio especialista pode
transferir para outro quando o pedido nao e da area dele.

A transferencia e decidida pelo orquestrador, nao pela ferramenta: o modelo
apenas *pede* o repasse, e aqui validamos destino, contamos saltos e evitamos
que dois agentes fiquem devolvendo a conversa um para o outro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from langchain_core.tools import BaseTool, StructuredTool
from loguru import logger
from pydantic import BaseModel, Field

from ..core.config import get_settings
from ..models.schemas import LLMResponse, Message
from . import langchain_agent_service, mcp_service
from .assistant_tools import ASSISTANT_TOOLS
from .llm_routing_service import pick_auto_llm

settings = get_settings()

HANDOFF_TOOL_NAME = "transfer_to_agent"


@dataclass(frozen=True)
class Specialist:
    id: str
    label: str
    description: str
    instructions: str
    routing_task: str
    tool_names: tuple[str, ...] = ()
    use_mcp: bool = False


SPECIALISTS: dict[str, Specialist] = {
    "general": Specialist(
        id="general",
        label="Generalista",
        description="conversa geral, duvidas amplas e pedidos que nao se "
                    "encaixam nas outras especialidades",
        instructions=(
            "Voce e o agente generalista. Responda de forma direta e pratica. "
            "Se o pedido for claramente de codigo, de aulas gravadas ou de "
            "agenda, transfira para o agente correspondente em vez de "
            "responder por conta propria."
        ),
        routing_task="general",
        use_mcp=True,
    ),
    "code": Specialist(
        id="code",
        label="Codigo",
        description="programacao, leitura de workspace, scripts, erros e "
                    "revisao de codigo",
        instructions=(
            "Voce e o agente de codigo. Trabalhe com o contexto real do "
            "workspace quando ele estiver na mensagem e proponha passos "
            "pequenos e verificaveis. Nao execute nada: proponha e deixe a "
            "interface confirmar."
        ),
        routing_task="code",
        tool_names=(
            "propose_coding_action",
            "propose_computer_action",
            "propose_project_action",
        ),
        use_mcp=True,
    ),
    "study": Specialist(
        id="study",
        label="Estudos",
        description="aulas gravadas, materias, resumos e conteudo de estudo",
        instructions=(
            "Voce e o agente de estudos. Responda com base nos trechos de aula "
            "fornecidos no contexto, citando disciplina e data. Se os trechos "
            "nao cobrirem a pergunta, diga o que falta em vez de supor."
        ),
        routing_task="study",
    ),
    "calendar": Specialist(
        id="calendar",
        label="Agenda",
        description="compromissos, reunioes, eventos e disponibilidade",
        instructions=(
            "Voce e o agente de agenda. Trate datas e horarios com precisao e "
            "confirme o que ficou entendido antes de propor um evento."
        ),
        routing_task="calendar",
        tool_names=("propose_calendar_event",),
    ),
}

DEFAULT_SPECIALIST = "general"

_TASK_TO_SPECIALIST = {
    "code": "code",
    "study": "study",
    "calendar": "calendar",
    "general": "general",
}


class HandoffInput(BaseModel):
    agent: str = Field(description="id do agente que deve assumir")
    reason: str = Field(default="", description="por que a transferencia")


@dataclass
class AgentOutcome:
    response: LLMResponse
    agent_id: str
    provider: str
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    handoffs: list[dict[str, str]] = field(default_factory=list)


def select_specialist(task: str) -> Specialist:
    return SPECIALISTS[_TASK_TO_SPECIALIST.get(task, DEFAULT_SPECIALIST)]


def _handoff_tool(current: str) -> BaseTool:
    """Ferramenta A2A, com a lista de destinos montada em tempo de execucao."""
    others = [item for item in SPECIALISTS.values() if item.id != current]
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


async def build_tools(
    specialist: Specialist,
    *,
    allow_handoff: bool,
) -> list[BaseTool]:
    tools: list[BaseTool] = []

    if specialist.tool_names:
        by_name = {tool.name: tool for tool in ASSISTANT_TOOLS}
        tools.extend(
            by_name[name] for name in specialist.tool_names if name in by_name
        )

    if specialist.use_mcp:
        try:
            tools.extend(await mcp_service.get_tools())
        except Exception as e:
            logger.warning(f"Ferramentas MCP indisponiveis: {e}")

    if allow_handoff:
        tools.append(_handoff_tool(specialist.id))

    return tools


def _find_handoff(trace: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(list(trace)):
        if entry.get("tool") == HANDOFF_TOOL_NAME:
            return entry
    return None


async def run_agents(
    *,
    message: str,
    history: list[Message],
    system_prompt: str,
    task: str,
    active_llms: list[str],
    requested_llm: str | None = None,
) -> AgentOutcome:
    """Roda o especialista escolhido, seguindo transferencias ate o teto."""
    specialist = select_specialist(task)
    visited = {specialist.id}
    handoffs: list[dict[str, str]] = []
    tool_trace: list[dict[str, Any]] = []
    max_handoffs = max(0, settings.agent_max_handoffs)

    provider = requested_llm or ""
    response = LLMResponse(llm="backend", content="", is_error=True)

    for hop in range(max_handoffs + 1):
        provider = requested_llm or await pick_auto_llm(
            active_llms, specialist.routing_task
        )
        if not provider:
            return AgentOutcome(
                response=LLMResponse(
                    llm="backend",
                    content="Nenhum agente de IA esta disponivel agora.",
                    is_error=True,
                ),
                agent_id=specialist.id,
                provider="",
            )

        allow_handoff = hop < max_handoffs
        tools = await build_tools(specialist, allow_handoff=allow_handoff)

        response, trace = await langchain_agent_service.run_with_tools(
            provider,
            message,
            history,
            f"{system_prompt}\n\n{specialist.instructions}",
            tools,
            max_iterations=max(1, settings.agent_max_tool_iterations),
            stop_tools={HANDOFF_TOOL_NAME} if allow_handoff else set(),
        )
        tool_trace.extend(trace)

        handoff = _find_handoff(trace)
        if handoff is None:
            break

        target_id = str((handoff.get("args") or {}).get("agent") or "").strip()
        target = SPECIALISTS.get(target_id)
        # Destino invalido ou ja visitado encerra o repasse: sem isso, dois
        # agentes podem empurrar a conversa um para o outro ate o teto.
        if target is None or target.id in visited:
            logger.info(
                f"Transferencia ignorada ({specialist.id} -> {target_id or 'vazio'})"
            )
            break

        handoffs.append({
            "from": specialist.id,
            "to": target.id,
            "reason": str((handoff.get("args") or {}).get("reason") or ""),
        })
        visited.add(target.id)
        specialist = target

    return AgentOutcome(
        response=response,
        agent_id=specialist.id,
        provider=provider,
        tool_trace=tool_trace,
        handoffs=handoffs,
    )
