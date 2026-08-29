"""Nos que geram resposta com modelo: `single`, `multi` e `chain`.

Os tres compartilham a mesma pergunta de entrada - ha provedor disponivel para
atender? - e a mesma resposta quando nao ha. O que muda e como o pedido e
distribuido: um especialista com ferramentas, varios provedores em paralelo, ou
provedores encadeados refinando a resposta anterior.

O ramo `single` e o unico que passa pelo subgrafo de agente. `multi` e `chain`
sao comparacao e refinamento entre provedores, nao trabalho de especialista:
dar ferramenta a eles multiplicaria efeito colateral por N sem melhorar a
resposta.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...core.observability import span
from ...models.schemas import LLMResponse
from ..state import ChatGraphState, ChatRuntimeContext


async def unavailable_response(llm: str | None = None) -> LLMResponse:
    """Explica por que nao ha resposta, com o detalhe do provedor quando houver."""
    from ...services.llm_status_service import get_llm_statuses
    from ...services.user_llm_config_service import runtime_settings

    if llm:
        statuses = await get_llm_statuses()
        status = statuses.get(llm)
        detail = status.error if status and status.error else "servico indisponivel"
        return LLMResponse(
            llm=llm,
            content=(
                f"{runtime_settings.llm_labels.get(llm, llm)} nao esta online "
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


async def _providers(context: ChatRuntimeContext, task: str) -> list[str] | None:
    """Provedores a usar, ou `None` quando nao ha nenhum atendendo.

    Um provedor pedido explicitamente que nao esta ativo devolve lista vazia -
    e o chamador transforma isso na explicacao daquele provedor, e nao numa
    troca silenciosa por outro.
    """
    from ...services.llm_routing_service import rank_auto_llms

    if context.requested_llm:
        return (
            [context.requested_llm]
            if context.requested_llm in context.active_llms
            else []
        )
    ranked = await rank_auto_llms(
        list(context.active_llms), task, available_only=True
    )
    return ranked or None


def build_dispatch_single(run_agents=None):
    """No `single`: entrega ao subgrafo de agente, com ferramentas e handoff.

    Args:
        run_agents: executor injetado; `None` resolve o padrao **na hora da
            chamada**, e nao na construcao do grafo. A diferenca importa: o
            grafo e compilado no import, e amarrar a funcao ali congelaria a
            implementacao para o processo inteiro.
    """

    async def dispatch_single(
        state: ChatGraphState,
        runtime: Runtime[ChatRuntimeContext],
    ) -> dict[str, Any]:
        context = runtime.context
        task = state.get("task_kind") or "general"

        if context.requested_llm and context.requested_llm not in context.active_llms:
            return {"responses": [await unavailable_response(context.requested_llm)]}
        if not context.requested_llm and not context.active_llms:
            return {"responses": [await unavailable_response()]}

        executor = run_agents or _default_run_agents()
        async with span("graph.dispatch_single", "node", task=task):
            outcome = await executor(
                message=state["message"],
                history=state["history"],
                system_prompt=state["system_prompt"],
                task=task,
                active_llms=list(context.active_llms),
                requested_llm=context.requested_llm,
            )
        return {
            "responses": [outcome.response],
            "agent_id": outcome.agent_id,
            "tool_trace": outcome.tool_trace,
            "handoffs": outcome.handoffs,
        }

    return dispatch_single


def build_dispatch_multi(dispatch=None):
    """No `multi`: mesma pergunta para varios provedores, em paralelo."""

    async def dispatch_multi(
        state: ChatGraphState,
        runtime: Runtime[ChatRuntimeContext],
    ) -> dict[str, Any]:
        context = runtime.context
        if context.requested_llm and context.requested_llm not in context.active_llms:
            return {"responses": [await unavailable_response(context.requested_llm)]}

        llms = await _providers(context, state.get("task_kind") or "general")
        if not llms:
            return {"responses": [await unavailable_response()]}

        send = dispatch or _default_dispatch("dispatch_multi")
        async with span("graph.dispatch_multi", "node", providers=len(llms)):
            responses = await send(
                llms, state["message"], state["history"], state["system_prompt"]
            )
        return {"responses": responses}

    return dispatch_multi


def build_dispatch_chain(dispatch=None):
    """No `chain`: provedores encadeados, cada um refinando o anterior."""

    async def dispatch_chain(
        state: ChatGraphState,
        runtime: Runtime[ChatRuntimeContext],
    ) -> dict[str, Any]:
        context = runtime.context
        if context.requested_llm and context.requested_llm not in context.active_llms:
            return {"responses": [await unavailable_response(context.requested_llm)]}

        llms = await _providers(context, state.get("task_kind") or "general")
        if not llms:
            return {"responses": [await unavailable_response()]}

        send = dispatch or _default_dispatch("dispatch_chain")
        async with span("graph.dispatch_chain", "node", providers=len(llms)):
            response = await send(
                llms, state["message"], state["history"], state["system_prompt"]
            )
        return {"responses": [response]}

    return dispatch_chain


def _default_run_agents():
    """O executor de agentes padrao, resolvido no momento da chamada."""
    from ...services import agent_service

    return agent_service.run_agents


def _default_dispatch(name: str):
    """O despacho padrao a provedores, resolvido no momento da chamada."""
    from ...services import langchain_agent_service

    return getattr(langchain_agent_service, name)
