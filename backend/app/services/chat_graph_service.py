from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from loguru import logger

from ..core.config import get_settings
from ..core.database import AsyncSessionLocal
from ..models.schemas import (
    LLMResponse,
    Message,
    ResponseModeEnum,
    ShortcutRegistrationAction,
)
from . import langchain_agent_service
from .assistant_tools import invoke_action_tool, invoke_calendar_action_tool
from .calendar_query_service import (
    execute_calendar_query,
    format_calendar_query_response,
    interpret_calendar_query,
)
from .launcher_service import (
    build_auto_registration_from_launch,
    build_launch_action,
    build_launch_context,
    build_registration_context,
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
    "calendar",
    "calendar_query",
]
GraphRoute = Literal["action", "calendar_query", "single", "multi", "chain"]


class ChatGraphState(TypedDict, total=False):
    message: str
    history: list[Message]
    mode: ResponseModeEnum
    requested_llm: str | None
    active_llms: list[str]
    system_prompt: str
    tutor_id: str
    user_id: str
    timezone: str
    action: Any
    action_kind: ActionKind
    responses: list[LLMResponse]


settings = get_settings()

_MONTH_NAMES_PT = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def _value(action: Any, key: str, default: Any = "") -> Any:
    if isinstance(action, dict):
        return action.get(key, default)
    return getattr(action, key, default)


def _calendar_proposal_text(action: Any) -> str:
    start = datetime.fromisoformat(str(_value(action, "start_time")))
    day = f"{start.day} de {_MONTH_NAMES_PT[start.month - 1]} de {start.year}"
    hour_label = "1 hora" if start.hour == 1 else f"{start.hour} horas"
    if start.minute:
        minute_label = "1 minuto" if start.minute == 1 else f"{start.minute} minutos"
        hour_label = f"{hour_label} e {minute_label}"
    return (
        f"Preparei o evento “{_value(action, 'title')}” para {day}, "
        f"às {hour_label}. Os detalhes estão prontos para criação."
    )


async def _detect_action(state: ChatGraphState) -> dict[str, Any]:
    message = state["message"]
    system_prompt = state["system_prompt"]

    calendar_action = invoke_calendar_action_tool(
        message,
        state.get("timezone", "America/Sao_Paulo"),
    )
    if calendar_action:
        return {
            "action": calendar_action,
            "action_kind": "calendar",
        }

    calendar_query = await interpret_calendar_query(
        message,
        history=state.get("history", []),
        timezone_name=state.get("timezone", "America/Sao_Paulo"),
        requested_llm=state.get("requested_llm"),
        active_llms=state.get("active_llms", []),
    )
    if calendar_query:
        return {
            "action": calendar_query.model_dump(mode="json"),
            "action_kind": "calendar_query",
        }

    for action_kind in ("computer", "coding", "project", "registration"):
        action = invoke_action_tool(action_kind, message)
        if action:
            update: dict[str, Any] = {
                "action": action,
                "action_kind": action_kind,
            }
            if action_kind == "registration":
                update["system_prompt"] = (
                    system_prompt
                    + build_registration_context(
                        ShortcutRegistrationAction.model_validate(action)
                    )
                )
            return update

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
    if state.get("action_kind") == "calendar_query":
        return "calendar_query"
    if state.get("action_kind") in {
        "computer",
        "coding",
        "project",
        "registration",
        "calendar",
    }:
        return "action"
    return cast(GraphRoute, state["mode"].value)


async def _query_calendar(state: ChatGraphState) -> dict[str, Any]:
    from .calendar_query_service import CalendarQueryPlan

    try:
        plan = CalendarQueryPlan.model_validate(state["action"])
        result = await execute_calendar_query(state["user_id"], plan)
        content = format_calendar_query_response(plan, result)
        response = LLMResponse(llm="backend", content=content)
    except Exception:
        response = LLMResponse(
            llm="backend",
            content=(
                "Não consegui consultar sua agenda agora. "
                "Verifique a conta em Configurações > Agendas e tente novamente."
            ),
            is_error=True,
        )
    return {"responses": [response], "action": None}


async def _acknowledge_action(state: ChatGraphState) -> dict[str, Any]:
    action = state["action"]
    action_kind = state["action_kind"]

    if action_kind == "calendar":
        content = _calendar_proposal_text(action)
    elif action_kind == "computer":
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
        response = await langchain_agent_service.dispatch_single(
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

    responses = await langchain_agent_service.dispatch_multi(
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

    response = await langchain_agent_service.dispatch_chain(
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
    workflow.add_node("query_calendar", _query_calendar)
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
    user_id: str = "",
    timezone: str = "America/Sao_Paulo",
) -> ChatGraphState:
    try:
        result = await chat_graph.ainvoke(
            {
                "message": message,
                "history": history,
                "mode": mode,
                "requested_llm": requested_llm,
                "active_llms": list(active_llms),
                "system_prompt": system_prompt,
                "tutor_id": tutor_id,
                "user_id": user_id,
                "timezone": timezone,
            }
        )
        return cast(ChatGraphState, result)
    except Exception as exc:
        logger.exception("Chat graph failed: {}", exc)
        return {
            "action_kind": "chat",
            "action": None,
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
