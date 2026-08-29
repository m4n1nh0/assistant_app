"""agent-orchestrator: o grafo do chat exposto como servico proprio.

Este entrypoint existe para manter a opcao aberta, e nao porque a extracao ja se
justifique. Vale registrar o motivo, porque ele e o tipo de coisa que se perde:

as credenciais de nuvem de cada usuario sao decifradas por requisicao e vivem em
`ContextVar` durante ela. Rodar o orquestrador em outro processo obrigaria a
trafegar chave decifrada entre servicos - piorando a seguranca para ganhar
isolamento que, num backend que roda na maquina do usuario, nao resolve
problema nenhum.

Enquanto isso nao muda, o grafo roda dentro do `assistant-api`. Este servico
serve para dois casos legitimos: teste de carga isolado do fluxo agentivo, e
uma futura implantacao em que a API e o orquestrador escalem separado - ai o
contrato ja existe e a migracao e de configuracao.
"""

from __future__ import annotations

from typing import Any

from fastapi import Body

from app.core.config import get_settings
from app.models.schemas import Message, ResponseModeEnum
from app.orchestration.graph import chat_graph, graph_state, run_chat_graph

from ..common import create_service, serve

settings = get_settings()


async def _ready() -> dict[str, Any]:
    """Pronto quando o grafo compilou e os nos esperados existem."""
    nodes = set(chat_graph.get_graph().nodes)
    expected = {"detect_action", "retrieve_context", "dispatch_single"}
    return {
        "ok": expected <= nodes,
        "nodes": sorted(nodes),
        "checkpointing": settings.checkpoint_backend,
    }


app = create_service(
    name="agent-orchestrator",
    title="Agent Orchestrator",
    description=(
        "Orquestracao stateful do fluxo agentivo com LangGraph: roteamento, "
        "decisoes, handoff entre agentes, checkpoint e retomada."
    ),
    ready_check=_ready,
)


@app.post("/orchestrate/chat")
async def orchestrate_chat(body: dict[str, Any] = Body(...)):
    """Roda o grafo do chat para uma mensagem.

    O corpo espelha os argumentos de `run_chat_graph`. As credenciais nao
    trafegam aqui: o processo que responder por esta rota precisa carregar o
    proprio contexto de provedores.
    """
    result = await run_chat_graph(
        message=str(body.get("message") or ""),
        history=[Message.model_validate(item) for item in body.get("history") or []],
        mode=ResponseModeEnum(body.get("mode") or "single"),
        requested_llm=body.get("requested_llm"),
        active_llms=list(body.get("active_llms") or []),
        system_prompt=str(body.get("system_prompt") or ""),
        tutor_id=str(body.get("tutor_id") or ""),
        user_id=str(body.get("user_id") or ""),
        timezone=str(body.get("timezone") or "America/Sao_Paulo"),
        conversation_id=str(body.get("conversation_id") or ""),
        execution_id=str(body.get("execution_id") or ""),
    )
    return {
        "action_kind": result.get("action_kind"),
        "action": result.get("action"),
        "responses": [item.model_dump() for item in result.get("responses") or []],
        "agent_id": result.get("agent_id", ""),
        "tool_trace": result.get("tool_trace") or [],
        "handoffs": result.get("handoffs") or [],
        "errors": result.get("errors") or [],
        "execution_id": result.get("execution_id", ""),
    }


@app.get("/orchestrate/state/{conversation_id}")
async def orchestrate_state(conversation_id: str, tutor_id: str = ""):
    """Estado gravado de uma conversa, para diagnostico e retomada."""
    return await graph_state(conversation_id=conversation_id, tutor_id=tutor_id)


def main() -> None:
    """Sobe o orquestrador na porta configurada."""
    serve("services.orchestrator.main:app", port=settings.orchestrator_port)


if __name__ == "__main__":
    main()
