"""No de RAG: classifica a tarefa e busca material de aula quando for estudo.

A busca vetorial so roda no ramo de conversa e so quando o pedido e de estudo.
Acao local e consulta de agenda ja tem resposta propria, e pagar uma busca em
toda mensagem encareceria o caminho mais comum sem melhorar resposta nenhuma.

O no nao conhece Qdrant nem o servico de educacao: ele recebe um
`RetrievalGateway`. Trocar o vector store, ou testar o no com um fake, nao
encosta neste arquivo.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...core.observability import span
from ...ports.retrieval import RetrievalGateway, RetrievedChunk
from ..state import NON_CHAT_KINDS, ChatGraphState, ChatRuntimeContext

_STUDY_LIMIT = 6
_STUDY_MIN_SCORE = 0.25

_PREAMBLE = (
    "\n\nTrechos das aulas gravadas pelo usuario que podem responder a "
    "pergunta. Use-os como fonte e cite a disciplina e a data quando "
    "responder. Se nao responderem o que foi perguntado, diga isso em vez "
    "de completar com suposicao.\n"
)


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Transforma os trechos recuperados no bloco que entra no prompt."""
    if not chunks:
        return ""
    lines = [f"[{chunk.reference or chunk.source}] {chunk.content}" for chunk in chunks]
    return _PREAMBLE + "\n".join(lines)


def build_retrieve_context(retrieval: RetrievalGateway | None = None):
    """Cria o no de RAG amarrado a um gateway de busca.

    Args:
        retrieval: porta de acesso a busca semantica; `None` resolve o gateway
            do processo na hora da chamada, para o grafo compilado no import
            nao congelar a implementacao.

    Returns:
        A corrotina do no, pronta para `add_node`.
    """

    async def retrieve_context(
        state: ChatGraphState,
        runtime: Runtime[ChatRuntimeContext],
    ) -> dict[str, Any]:
        from ...services.llm_routing_service import detect_task

        if state.get("action_kind") in NON_CHAT_KINDS:
            return {}

        task = detect_task(state["message"])
        update: dict[str, Any] = {"task_kind": task}

        tenant_id = runtime.context.tutor_id
        if task != "study" or not tenant_id:
            return update

        async with span("graph.retrieve_context", "rag", task=task) as observed:
            try:
                gateway = retrieval or _default_gateway()
                chunks = await _search(gateway, state["message"], tenant_id)
            except Exception as exc:
                # Falha de indice nao pode calar a resposta: o modelo responde
                # do conhecimento geral, que e degradacao aceitavel.
                observed.fail(exc)
                return {
                    **update,
                    "errors": list(state.get("errors") or [])
                    + [f"busca de aula falhou: {exc}"],
                }
            observed.set(chunks=len(chunks))

        context = format_context(chunks)
        if context:
            update["system_prompt"] = state["system_prompt"] + context
        return update

    return retrieve_context


async def _search(
    retrieval: RetrievalGateway,
    message: str,
    tenant_id: str,
) -> list[RetrievedChunk]:
    """Busca com reindexacao de recuperacao, quando o gateway oferecer."""
    catch_up = getattr(retrieval, "search_with_catch_up", None)
    if catch_up is not None:
        return await catch_up(
            message,
            tenant_id=tenant_id,
            limit=_STUDY_LIMIT,
            min_score=_STUDY_MIN_SCORE,
        )
    return await retrieval.search(
        message,
        tenant_id=tenant_id,
        limit=_STUDY_LIMIT,
        min_score=_STUDY_MIN_SCORE,
    )


def _default_gateway() -> RetrievalGateway:
    """O gateway de busca do processo, resolvido no momento da chamada."""
    from ...adapters.container import get_retrieval_gateway

    return get_retrieval_gateway()
