"""Nos que decidem se a mensagem vira acao local em vez de resposta em texto.

A ordem da deteccao importa e nao e arbitraria: acao vem antes de resposta em
texto porque um pedido como "abre o VS Code" deve virar acao para a interface
executar, e nao um paragrafo explicando como abrir o VS Code.

As ferramentas de acao sao chamadas aqui **sem passar pelo modelo**: sao
construtoras determinísticas, e gastar uma chamada de LLM para decidir se
"verifique meu IP" e um diagnostico de rede seria pagar por uma decisao que uma
expressao regular resolve.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...core.observability import span
from ...models.schemas import ShortcutRegistrationAction
from ..state import ChatGraphState, ChatRuntimeContext

# A interface embrulha algumas mensagens com contexto local (workspace, janela).
# Esses blocos disparam falso positivo nos detectores por palavra-chave - "ip"
# dentro do codigo fonte vira diagnostico de rede, "vscode-projects" no caminho
# vira atalho - entao a deteccao de acao e pulada para eles.
_LOCAL_CONTEXT_MARKERS = (
    "contexto local do workspace",
    "contexto automatico do workspace",
    "contexto da janela",
)


def is_context_wrapped(message: str) -> bool:
    """Diz se a mensagem e um blob de contexto local montado pela interface."""
    head = message[:600].lower()
    return any(marker in head for marker in _LOCAL_CONTEXT_MARKERS)


async def detect_action(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, Any]:
    """Classifica a mensagem em uma das rotas de acao, ou deixa em aberto."""
    from ...services.assistant_tools import (
        invoke_action_tool,
        invoke_calendar_action_tool,
    )
    from ...services.calendar_query_service import interpret_calendar_query
    from ...services.education_action_service import build_education_open_action
    from ...services.launcher_service import build_registration_context

    message = state["message"]
    context = runtime.context

    async with span("graph.detect_action", "node") as observed:
        if is_context_wrapped(message):
            observed.set(kind="chat", reason="contexto local")
            return {"action_kind": "chat"}

        education_action = build_education_open_action(message)
        if education_action:
            observed.set(kind="education")
            return {
                "action": education_action.model_dump(mode="json"),
                "action_kind": "education",
            }

        calendar_action = invoke_calendar_action_tool(message, context.timezone)
        if calendar_action:
            observed.set(kind="calendar")
            return {"action": calendar_action, "action_kind": "calendar"}

        calendar_query = await interpret_calendar_query(
            message,
            history=state.get("history", []),
            timezone_name=context.timezone,
            requested_llm=context.requested_llm,
            active_llms=list(context.active_llms),
        )
        if calendar_query:
            observed.set(kind="calendar_query")
            return {
                "action": calendar_query.model_dump(mode="json"),
                "action_kind": "calendar_query",
            }

        for action_kind in ("computer", "coding", "project", "registration"):
            action = invoke_action_tool(action_kind, message)
            if not action:
                continue
            observed.set(kind=action_kind)
            update: dict[str, Any] = {
                "action": action,
                "action_kind": action_kind,
            }
            if action_kind == "registration":
                update["system_prompt"] = state["system_prompt"] + (
                    build_registration_context(
                        ShortcutRegistrationAction.model_validate(action)
                    )
                )
            return update

        observed.set(kind="unresolved")
        return {"action_kind": "unresolved"}


async def lookup_shortcut(
    message: str,
    tutor_id: str,
) -> tuple[Any | None, str, str]:
    """Procura um atalho cadastrado que corresponda ao pedido.

    Returns:
        `(acao, tipo, contexto)`. Sem atalho e sem cadastro automatico, devolve
        `(None, "chat", "")` e a conversa segue para o modelo.
    """
    from ...core.database import AsyncSessionLocal
    from ...services.launcher_service import (
        build_auto_registration_from_launch,
        build_launch_action,
        build_launch_context,
        build_registration_context,
        find_shortcut_in_message,
    )

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


async def resolve_shortcut(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, Any]:
    """Tenta casar a mensagem com um atalho quando nada foi resolvido antes."""
    if state.get("action_kind") != "unresolved":
        return {}

    async with span("graph.resolve_shortcut", "node") as observed:
        try:
            action, action_kind, context = await lookup_shortcut(
                state["message"], runtime.context.tutor_id
            )
        except Exception as exc:
            # Banco fora do ar nao pode calar o chat: sem atalho, a conversa
            # segue para o modelo.
            observed.fail(exc)
            return {
                "action_kind": "chat",
                "errors": list(state.get("errors") or [])
                + [f"busca de atalho falhou: {exc}"],
            }

        observed.set(kind=action_kind)
        update: dict[str, Any] = {"action_kind": action_kind}
        if action is not None:
            update["action"] = action
        if context:
            update["system_prompt"] = state["system_prompt"] + context
        return update
