from __future__ import annotations

from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .coding_action_service import build_coding_action
from .computer_action_service import build_computer_action
from .launcher_service import (
    build_project_open_action,
    build_shortcut_registration_action,
)


class ActionToolInput(BaseModel):
    request: str = Field(
        min_length=1,
        description="Pedido original do usuario que pode exigir uma acao local.",
    )


class StructuredActionResult(BaseModel):
    matched: bool
    action: dict[str, Any] | None = None


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


ASSISTANT_TOOLS: tuple[BaseTool, ...] = (
    propose_computer_action,
    propose_coding_action,
    propose_project_action,
    propose_shortcut_registration,
)

ACTION_TOOLS: dict[str, BaseTool] = {
    "computer": propose_computer_action,
    "coding": propose_coding_action,
    "project": propose_project_action,
    "registration": propose_shortcut_registration,
}


def invoke_action_tool(kind: str, request: str) -> dict[str, Any] | None:
    tool_instance = ACTION_TOOLS[kind]
    result = tool_instance.invoke({"request": request})
    if isinstance(result, StructuredActionResult):
        return result.action if result.matched else None
    parsed = StructuredActionResult.model_validate(result)
    return parsed.action if parsed.matched else None
