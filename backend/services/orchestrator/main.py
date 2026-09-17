"""agent-orchestrator: o grafo do chat como servico proprio.

A assistant-api continua sendo a porta do produto - autentica, monta persona e
historico, grava a conversa - e, com `ORCHESTRATOR_TRANSPORT=remote`, entrega
cada turno aqui. O que antes impedia a extracao e resolvido assim:

- **Credenciais**: nao trafegam. O turno traz o `tutor_id`, e este processo
  decifra as chaves daquele usuario do banco, com a mesma
  `CREDENTIAL_ENCRYPTION_KEY`, ativando-as num `ContextVar` so pela duracao do
  turno - exatamente como a API faz.
- **Maquina do usuario**: o manifesto validado vem no turno e vira o catalogo
  daquela maquina aqui. A execucao volta a API (`ASSISTANT_API_URL`), que e
  quem tem o WebSocket da sessao.
- **Autenticacao**: `X-Internal-Token`. O servico nao tem usuario proprio e nao
  deve ter dominio publico; o token cobre o erro de expor mesmo assim.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from loguru import logger

from app.adapters.devices.callback import DeviceCapabilityCallback
from app.adapters.orchestration.wire import (
    manifest_from_payload,
    result_to_payload,
    turn_from_payload,
)
from app.core.config import get_settings
from app.core.internal_auth import require_internal_token
from app.core.observability import bind
from app.orchestration.graph import chat_graph, graph_state, run_chat_graph
from app.services.device_catalog_service import bind_device, get_device_catalog, reset_device
from app.services.user_llm_config_service import (
    activate_user_llms,
    load_user_llm_runtime,
    reset_user_llms,
)

from ..common import create_service, serve

settings = get_settings()

#: Leva capacidade da maquina de volta a API. Um por processo: nao guarda estado
#: de requisicao, so endereco e token.
device_callback = DeviceCapabilityCallback(
    settings.assistant_api_base_url,
    token=settings.internal_service_token,
)


async def _ready() -> dict[str, Any]:
    """Pronto quando o grafo compilou e o servico sabe atender turno."""
    nodes = set(chat_graph.get_graph().nodes)
    expected = {"detect_action", "retrieve_context", "dispatch_single"}
    token = bool(settings.internal_service_token.strip())
    return {
        # Sem token toda requisicao e recusada: o processo esta vivo, mas nao
        # esta pronto.
        "ok": expected <= nodes and token,
        "nodes": sorted(nodes),
        "checkpointing": settings.checkpoint_backend,
        "internal_token_configured": token,
        "assistant_api": settings.assistant_api_base_url,
    }


async def _startup() -> None:
    if not settings.internal_service_token.strip():
        logger.error(
            "INTERNAL_SERVICE_TOKEN vazio: o agent-orchestrator vai recusar "
            "todos os turnos ate que o mesmo valor da assistant-api seja definido"
        )
    if not settings.assistant_api_url.strip():
        logger.warning(
            "ASSISTANT_API_URL vazio: capacidades da maquina do usuario vao "
            f"tentar {settings.assistant_api_base_url}"
        )


app = create_service(
    name="agent-orchestrator",
    title="Agent Orchestrator",
    description=(
        "Orquestracao stateful do fluxo agentivo com LangGraph: roteamento, "
        "decisoes, handoff entre agentes, checkpoint e retomada."
    ),
    ready_check=_ready,
    on_startup=_startup,
)

router = APIRouter(dependencies=[Depends(require_internal_token)])


@router.post("/orchestrate/chat")
async def orchestrate_chat(body: dict[str, Any] = Body(...)):
    """Roda o grafo do chat para um turno enviado pela assistant-api."""
    turn = turn_from_payload(body)
    manifest = manifest_from_payload(body.get("device"))

    catalog = get_device_catalog()
    if manifest is not None:
        # Republicar a cada turno mantem o catalogo igual ao que a maquina
        # declarou por ultimo na API, sem canal extra de sincronizacao.
        catalog.publish(manifest, device_callback.runner_factory())
    elif turn.device_id:
        # A API nao mandou manifesto: a maquina desconectou ou nunca publicou.
        catalog.drop(turn.device_id)

    runtime_token = activate_user_llms(await load_user_llm_runtime(turn.tutor_id))
    device_token = bind_device(turn.device_id)
    try:
        with bind(
            conversation_id=turn.conversation_id,
            tenant_id=turn.tutor_id,
            user_id=turn.user_id,
        ):
            result = await run_chat_graph(**turn.graph_kwargs())
    finally:
        reset_device(device_token)
        reset_user_llms(runtime_token)
    return result_to_payload(result)


@router.get("/orchestrate/state/{conversation_id}")
async def orchestrate_state(conversation_id: str, tutor_id: str = ""):
    """Estado gravado de uma conversa, para diagnostico e retomada."""
    return await graph_state(conversation_id=conversation_id, tutor_id=tutor_id)


app.include_router(router)


def main() -> None:
    """Sobe o orquestrador na porta configurada."""
    serve("services.orchestrator.main:app", port=settings.orchestrator_port)


if __name__ == "__main__":
    main()
