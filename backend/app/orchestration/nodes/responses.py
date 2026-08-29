"""Nos que respondem sem passar por modelo: acao proposta e consulta de agenda.

Sao os dois ramos em que o backend ja sabe a resposta. Chamar um provedor aqui
seria gastar token para redigir uma frase que nao depende de raciocinio - e,
pior, abriria espaco para o modelo descrever uma acao diferente da que foi
realmente montada.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langgraph.runtime import Runtime

from ...core.observability import span
from ...models.schemas import LLMResponse
from ..state import ChatGraphState, ChatRuntimeContext

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


def calendar_proposal_text(action: Any) -> str:
    """Frase que descreve o evento montado, em portugues por extenso."""
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


async def acknowledge_action(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, Any]:
    """Confirma ao usuario a acao que a interface vai executar."""
    action = state["action"]
    action_kind = state["action_kind"]

    if action_kind == "calendar":
        content = calendar_proposal_text(action)
    elif action_kind == "education":
        destination = _value(action, "destination")
        content = (
            "Entendi que voce quer iniciar a chamada da turma. Posso abrir "
            "o Modo Aula diretamente na aba de presenca."
            if destination == "attendance"
            else "Entendi que a aula vai comecar. Posso abrir o Modo Aula "
            "diretamente na gravacao."
        )
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
        content = f"Vou cadastrar o atalho {_value(action, 'name')} {target_text}."

    return {"responses": [LLMResponse(llm="backend", content=content)]}


async def query_calendar(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, Any]:
    """Executa a consulta de agenda interpretada e formata o resultado.

    A acao e limpa no fim: o plano de consulta e detalhe interno do backend, e
    devolve-lo faria a interface tentar confirmar algo que ja foi executado.
    """
    from ...services.calendar_query_service import (
        CalendarQueryPlan,
        execute_calendar_query,
        format_calendar_query_response,
    )

    async with span("graph.query_calendar", "node") as observed:
        try:
            plan = CalendarQueryPlan.model_validate(state["action"])
            result = await execute_calendar_query(runtime.context.user_id, plan)
            content = format_calendar_query_response(plan, result)
            response = LLMResponse(llm="backend", content=content)
        except Exception as exc:
            observed.fail(exc)
            response = LLMResponse(
                llm="backend",
                content=(
                    "Não consegui consultar sua agenda agora. "
                    "Verifique a conta em Configurações > Agendas e tente novamente."
                ),
                is_error=True,
            )
    return {"responses": [response], "action": None}
