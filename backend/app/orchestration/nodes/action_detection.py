"""Nos que decidem se a mensagem vira acao local em vez de resposta em texto.

A ordem da deteccao importa e nao e arbitraria: acao vem antes de resposta em
texto porque um pedido como "abre o VS Code" deve virar acao para a interface
executar, e nao um paragrafo explicando como abrir o VS Code.

As ferramentas de acao sao chamadas aqui **sem passar pelo modelo**: sao
construtoras determinísticas, e gastar uma chamada de LLM para decidir se
"verifique meu IP" e um diagnostico de rede seria pagar por uma decisao que uma
expressao regular resolve.

O que mudou desde entao: quem diz o que existe passou a ser o catalogo publicado
pela maquina do usuario, e nao mais a lista escrita aqui. Este no continua sendo
o caminho rapido para as formas obvias de pedir - resposta sem round-trip de
modelo -, mas so atalha o que aquela maquina declarou saber fazer; o resto segue
para o modelo escolher no catalogo real (`machine_supports`).
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...core.observability import span
from ...models.schemas import ShortcutRegistrationAction
from ..state import ChatGraphState, ChatRuntimeContext

# A interface embrulha algumas mensagens com material que ela mesma coletou:
# contexto do workspace, contexto da janela e o resultado de uma acao local
# voltando para analise. Esses blocos disparam falso positivo nos detectores por
# palavra-chave - "ip" dentro do codigo fonte vira diagnostico de rede,
# "vscode-projects" no caminho vira atalho, "api.ipify.org" na saida do ipconfig
# vira inspecao de workspace - entao a deteccao de acao e pulada para eles.


def machine_supports(action_id: Any) -> bool:
    """Diz se a maquina desta sessao declarou saber executar aquela acao.

    A deteccao por palavra-chave e um **atalho** para as formas obvias de pedir,
    e nao mais a dona da decisao: quem lista o que existe e o catalogo publicado
    pela maquina. Enquanto uma sessao nao publicar catalogo - cliente antigo, ou
    canal ainda subindo - o atalho vale como antes, senao uma versao velha da
    interface perderia as acoes locais de uma hora para outra.
    """
    from ...services.device_catalog_service import get_device_catalog

    catalog = get_device_catalog()
    declared = catalog.descriptors()
    if not declared:
        return True
    if not action_id:
        return True
    return catalog.find(f"local_{action_id}") is not None


def is_context_wrapped(message: str) -> bool:
    """Diz se a mensagem e material local montado pela interface."""
    from ...services.local_message_markers import is_local_message

    return is_local_message(message)


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
            return {"action_kind": "chat", "action": None}

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

        for action_kind in ("computer", "coding", "project", "registration"):
            action = invoke_action_tool(action_kind, message)
            if not action:
                continue
            if not machine_supports(action.get("action_id")):
                # A maquina desta sessao publicou catalogo e essa capacidade nao
                # esta nele: o atalho por palavra-chave nao pode propor o que o
                # computador do usuario nao sabe fazer. Segue para o modelo, que
                # escolhe dentro do catalogo real.
                observed.set(skipped=action_kind, reason="fora do catalogo")
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

        # Consulta de agenda por ultimo entre os detectores: e o unico que
        # pergunta a um modelo, e ele le o historico. Rodando antes, uma pergunta
        # de agenda contaminava a conversa inteira - "verifique meu IP" depois de
        # "liste minha agenda" voltava como "nao encontrei conta de calendario",
        # e a resposta errada realimentava o historico. O que da para reconhecer
        # sem modelo decide primeiro; o modelo opina no que sobrou.
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

        observed.set(kind="unresolved")
        return {"action_kind": "unresolved", "action": None}


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
