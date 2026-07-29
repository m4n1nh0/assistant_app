from __future__ import annotations

from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from ..core.config import get_settings
from ..core.database import AsyncSessionLocal
from ..models.schemas import LLMResponse, Message, ResponseModeEnum
from . import llm_service
from .coding_action_service import build_coding_action
from .computer_action_service import build_computer_action
from .launcher_service import (
    build_auto_registration_from_launch,
    build_launch_action,
    build_launch_context,
    build_project_open_action,
    build_registration_context,
    build_shortcut_registration_action,
    find_shortcut_in_message,
)
from .llm_routing_service import pick_auto_llm
from .llm_status_service import get_llm_statuses


ActionKind = Literal[
    "unresolved",
    "chat",
    "launch",
    "computer",
    "coding",
    "project",
    "registration",
]
GraphRoute = Literal["action", "single", "multi", "chain"]


class ChatGraphState(TypedDict, total=False):
    message: str
    history: list[Message]
    mode: ResponseModeEnum
    requested_llm: str | None
    active_llms: list[str]
    system_prompt: str
    tutor_id: str
    action: Any
    action_kind: ActionKind
    responses: list[LLMResponse]


settings = get_settings()


def _value(action: Any, key: str, default: Any = "") -> Any:
    if isinstance(action, dict):
        return action.get(key, default)
    return getattr(action, key, default)


async def _detect_action(state: ChatGraphState) -> dict[str, Any]:
    message = state["message"]
    system_prompt = state["system_prompt"]

    computer_action = build_computer_action(message)
    if computer_action:
        return {
            "action": computer_action,
            "action_kind": "computer",
        }

    coding_action = build_coding_action(message)
    if coding_action:
        return {
            "action": coding_action,
            "action_kind": "coding",
        }

    project_action = build_project_open_action(message)
    if project_action:
        return {
            "action": project_action,
            "action_kind": "project",
        }

    registration_action = build_shortcut_registration_action(message)
    if registration_action:
        return {
            "action": registration_action,
            "action_kind": "registration",
            "system_prompt": (
                system_prompt + build_registration_context(registration_action)
            ),
        }

    return {"action_kind": "unresolved"}


async def _lookup_shortcut(
    message: str,
    tutor_id: str,
) -> tuple[Any | None, ActionKind, str]:
    async with AsyncSessionLocal() as db:
        shortcut = await find_shortcut_in_message(message, tutor_id, db)

    if shortcut:
        return (
            build_launch_action(shortcut),
            "launch",
            build_launch_context(shortcut),
        )

    auto_registration = build_auto_registration_from_launch(message)
    if auto_registration:
        return (
            auto_registration,
            "registration",
            build_registration_context(auto_registration),
        )

    return None, "chat", ""


async def _resolve_shortcut(state: ChatGraphState) -> dict[str, Any]:
    if state.get("action_kind") != "unresolved":
        return {}

    try:
        action, action_kind, context = await _lookup_shortcut(
            state["message"],
            state["tutor_id"],
        )
    except Exception:
        return {"action_kind": "chat"}

    update: dict[str, Any] = {"action_kind": action_kind}
    if action is not None:
        update["action"] = action
    if context:
        update["system_prompt"] = state["system_prompt"] + context
    return update


def _route_after_resolution(state: ChatGraphState) -> GraphRoute:
    if state.get("action_kind") in {
        "computer",
        "coding",
        "project",
        "registration",
    }:
        return "action"
    return cast(GraphRoute, state["mode"].value)


async def _acknowledge_action(state: ChatGraphState) -> dict[str, Any]:
    action = state["action"]
    action_kind = state["action_kind"]

    if action_kind == "computer":
        content = (
            f"Vou executar {_value(action, 'name')} no computador "
            "e analisar o resultado."
        )
    elif action_kind == "coding":
        content = (
            "Vou pedir para a interface inspecionar o workspace local: "
            f"{_value(action, 'name')}."
        )
    elif action_kind == "project":
        content = f"Vou abrir {_value(action, 'name')}."
    else:
        target_text = (
            "encontrando o app no computador"
            if not _value(action, "target")
            else "usando o destino informado"
        )
        content = (
            f"Vou cadastrar o atalho {_value(action, 'name')} "
            f"{target_text}."
        )

    return {
        "responses": [
            LLMResponse(
                llm="backend",
                content=content,
            )
        ]
    }


async def _unavailable_response(llm: str | None = None) -> LLMResponse:
    if llm:
        statuses = await get_llm_statuses()
        status = statuses.get(llm)
        detail = status.error if status and status.error else "servico indisponivel"
        return LLMResponse(
            llm=llm,
            content=(
                f"{settings.llm_labels.get(llm, llm)} nao esta online "
                f"para uso: {detail}"
            ),
            is_error=True,
        )

    return LLMResponse(
        llm="backend",
        content=(
            "Nenhum agente de IA esta disponivel agora. "
            "Para provedores em nuvem, verifique chave/saldo; para Ollama ou "
            "LocalAI, verifique o container, a URL interna e o modelo local."
        ),
        is_error=True,
    )


async def _dispatch_single(state: ChatGraphState) -> dict[str, Any]:
    active_llms = state["active_llms"]
    requested_llm = state.get("requested_llm")
    llm = (
        requested_llm
        if requested_llm
        else (await pick_auto_llm(active_llms) if active_llms else "")
    )

    if not llm:
        response = await _unavailable_response()
    elif llm not in active_llms:
        response = await _unavailable_response(llm)
    else:
        response = await llm_service.dispatch_single(
            llm,
            state["message"],
            state["history"],
            state["system_prompt"],
        )
    return {"responses": [response]}


async def _dispatch_multi(state: ChatGraphState) -> dict[str, Any]:
    active_llms = state["active_llms"]
    requested_llm = state.get("requested_llm")

    if requested_llm and requested_llm not in active_llms:
        return {"responses": [await _unavailable_response(requested_llm)]}

    llms = [requested_llm] if requested_llm else active_llms
    if not llms:
        return {"responses": [await _unavailable_response()]}

    responses = await llm_service.dispatch_multi(
        llms,
        state["message"],
        state["history"],
        state["system_prompt"],
    )
    return {"responses": responses}


async def _dispatch_chain(state: ChatGraphState) -> dict[str, Any]:
    active_llms = state["active_llms"]
    requested_llm = state.get("requested_llm")

    if requested_llm and requested_llm not in active_llms:
        return {"responses": [await _unavailable_response(requested_llm)]}

    llms = [requested_llm] if requested_llm else active_llms
    if not llms:
        return {"responses": [await _unavailable_response()]}

    response = await llm_service.dispatch_chain(
        llms,
        state["message"],
        state["history"],
        state["system_prompt"],
    )
    return {"responses": [response]}


def _build_chat_graph():
    workflow = StateGraph(ChatGraphState)
    workflow.add_node("detect_action", _detect_action)
    workflow.add_node("resolve_shortcut", _resolve_shortcut)
    workflow.add_node("acknowledge_action", _acknowledge_action)
    workflow.add_node("dispatch_single", _dispatch_single)
    workflow.add_node("dispatch_multi", _dispatch_multi)
    workflow.add_node("dispatch_chain", _dispatch_chain)

    workflow.add_edge(START, "detect_action")
    workflow.add_edge("detect_action", "resolve_shortcut")
    workflow.add_conditional_edges(
        "resolve_shortcut",
        _route_after_resolution,
        {
            "action": "acknowledge_action",
            "single": "dispatch_single",
            "multi": "dispatch_multi",
            "chain": "dispatch_chain",
        },
    )
    workflow.add_edge("acknowledge_action", END)
    workflow.add_edge("dispatch_single", END)
    workflow.add_edge("dispatch_multi", END)
    workflow.add_edge("dispatch_chain", END)
    return workflow.compile()


chat_graph = _build_chat_graph()


async def run_chat_graph(
    *,
    message: str,
    history: list[Message],
    mode: ResponseModeEnum,
    requested_llm: str | None,
    active_llms: list[str],
    system_prompt: str,
    tutor_id: str,
) -> ChatGraphState:
    result = await chat_graph.ainvoke(
        {
            "message": message,
            "history": history,
            "mode": mode,
            "requested_llm": requested_llm,
            "active_llms": list(active_llms),
            "system_prompt": system_prompt,
            "tutor_id": tutor_id,
        }
    )
    return cast(ChatGraphState, result)
