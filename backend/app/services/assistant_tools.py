"""Ferramentas LangChain que traduzem pedido do usuario em acao proposta.

Cada `propose_*` embrulha um construtor de acao (computador, codigo, projeto,
atalho, calendario) como ferramenta que o modelo pode chamar.

O nome importa: a ferramenta **propoe**, nunca executa. O backend so monta a
acao; quem executa e a interface, depois da confirmacao do usuario. Ferramenta
que nao reconhece o pedido devolve resultado vazio em vez de inventar acao.
"""

from __future__ import annotations

from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .calendar_action_service import build_calendar_create_action
from .coding_action_service import build_coding_action
from .computer_action_service import build_computer_action
from .launcher_service import (
    build_project_open_action,
    build_shortcut_registration_action,
)


class ActionToolInput(BaseModel):
    """Entrada padrao das ferramentas de acao: o pedido em linguagem natural."""
    request: str = Field(
        min_length=1,
        description="Pedido original do usuario que pode exigir uma acao local.",
    )


class StructuredActionResult(BaseModel):
    """Saida padrao: a acao montada, ou vazio quando o pedido nao foi reconhecido."""
    matched: bool
    action: dict[str, Any] | None = None


class CalendarActionToolInput(ActionToolInput):
    """Entrada da ferramenta de calendario, com o fuso necessario para datar o evento."""
    timezone: str = Field(
        default="America/Sao_Paulo",
        description="Fuso IANA usado para interpretar datas e horas locais.",
    )


def _structured_action(action: Any) -> StructuredActionResult:
    if action is None:
        return StructuredActionResult(matched=False)
    if hasattr(action, "model_dump"):
        action = action.model_dump(mode="json")
    return StructuredActionResult(matched=True, action=dict(action))


@tool("propose_computer_action", args_schema=ActionToolInput)
def propose_computer_action(request: str) -> StructuredActionResult:
    """Propoe diagnostico ou script local sem executar nada no computador."""
    return _structured_action(build_computer_action(request))


@tool("propose_coding_action", args_schema=ActionToolInput)
def propose_coding_action(request: str) -> StructuredActionResult:
    """Propoe inspecao segura de um workspace local para uma tarefa de codigo."""
    return _structured_action(build_coding_action(request))


@tool("propose_project_action", args_schema=ActionToolInput)
def propose_project_action(request: str) -> StructuredActionResult:
    """Propoe abrir um projeto local em uma IDE sem executar a abertura."""
    return _structured_action(build_project_open_action(request))


@tool("propose_shortcut_registration", args_schema=ActionToolInput)
def propose_shortcut_registration(request: str) -> StructuredActionResult:
    """Propoe cadastrar um atalho solicitado explicitamente pelo usuario."""
    return _structured_action(build_shortcut_registration_action(request))


@tool("propose_calendar_event", args_schema=CalendarActionToolInput)
def propose_calendar_event(
    request: str,
    timezone: str = "America/Sao_Paulo",
) -> StructuredActionResult:
    """Propoe um novo compromisso sem grava-lo antes da confirmacao do usuario."""
    return _structured_action(
        build_calendar_create_action(request, timezone_name=timezone)
    )


ASSISTANT_TOOLS: tuple[BaseTool, ...] = (
    propose_computer_action,
    propose_coding_action,
    propose_project_action,
    propose_shortcut_registration,
    propose_calendar_event,
)

ACTION_TOOLS: dict[str, BaseTool] = {
    "computer": propose_computer_action,
    "coding": propose_coding_action,
    "project": propose_project_action,
    "registration": propose_shortcut_registration,
}


def invoke_action_tool(kind: str, request: str) -> dict[str, Any] | None:
    """Chama diretamente o construtor de acao de um tipo, sem passar pelo modelo.

    Args:
        kind: tipo de acao (`computer`, `coding`, `project`, `registration`).
        request: pedido em linguagem natural.

    Returns:
        A acao montada, ou `None` quando o pedido nao corresponde aquele tipo.
    """
    tool_instance = ACTION_TOOLS[kind]
    result = tool_instance.invoke({"request": request})
    if isinstance(result, StructuredActionResult):
        return result.action if result.matched else None
    parsed = StructuredActionResult.model_validate(result)
    return parsed.action if parsed.matched else None


def invoke_calendar_action_tool(
    request: str,
    timezone: str,
) -> dict[str, Any] | None:
    """Chama o construtor de acao de calendario informando o fuso do usuario.

    Returns:
        A acao de criacao de evento, ou `None` quando nao ha pedido de agendamento.
    """
    result = propose_calendar_event.invoke(
        {"request": request, "timezone": timezone}
    )
    if isinstance(result, StructuredActionResult):
        return result.action if result.matched else None
    parsed = StructuredActionResult.model_validate(result)
    return parsed.action if parsed.matched else None
