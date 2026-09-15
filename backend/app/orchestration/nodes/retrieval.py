"""No de RAG: ancora a pergunta no cadastro de aulas e so entao busca material.

A ordem importa. Antes de perguntar ao indice vetorial "qual trecho parece com
isso?", o no pergunta ao banco relacional "essa disciplina existe? houve aula
nessa data? ela tem transcricao?". Sem essa ancora o vector store sempre devolve
o trecho mais parecido que tiver - mesmo que seja de outra disciplina ou de
outra semana - e a resposta sai confiante e errada.

Com a ancora, tres coisas mudam:

- a busca vetorial e restrita as aulas identificadas, em vez de varrer o
  semestre inteiro;
- quando a aula existe mas o indice esta atrasado, a transcricao e lida direto
  do banco, que e a fonte;
- quando nao ha aula, o modelo recebe isso escrito e responde "nao houve aula
  registrada nessa data" em vez de inventar conteudo.

O no nao conhece Qdrant: ele recebe um `RetrievalGateway`. Trocar o vector
store, ou testar o no com um fake, nao encosta neste arquivo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.runtime import Runtime

from ...core.observability import span
from ...ports.retrieval import RetrievalGateway, RetrievedChunk
from ..state import NON_CHAT_KINDS, ChatGraphState, ChatRuntimeContext

if TYPE_CHECKING:  # pragma: no cover - o import real e tardio, como o do banco
    from ...services.lesson_context_service import LessonScope

_STUDY_LIMIT = 6
_STUDY_MIN_SCORE = 0.25
# Pedido de visao geral le a aula inteira em vez do top-k: mais trechos, porque
# cada um cobre um pedaco maior do tempo de aula.
_OVERVIEW_LIMIT = 10
# Falas anteriores olhadas para herdar disciplina e data. Quatro cobrem a
# sequencia usual (pergunta, resposta, ajuste) sem arrastar assunto antigo.
_CONTEXT_TURNS = 4
# Com a aula ja identificada por disciplina e data, o corte pode ser mais baixo:
# o risco de colar trecho de outro assunto e o filtro por aula que resolve, nao
# o score. Exigir 0.25 aqui descartaria a propria aula pedida.
_ANCHORED_MIN_SCORE = 0.1
# Resumo cobre a aula inteira e come prompt; dois ja dao a visao geral.
_SUMMARY_LIMIT = 2

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
        errors: list[str] = list(state.get("errors") or [])

        tenant_id = runtime.context.tutor_id
        if not tenant_id:
            return update

        # A checagem relacional roda mesmo fora do ramo de estudo: e uma
        # consulta indexada numa tabela pequena, e e ela que descobre que
        # "banco de dados" na frase e uma disciplina cadastrada - coisa que a
        # heuristica de tarefa, que so olha palavra, nao tem como saber.
        scope, scope_error = await _scope(
            tenant_id,
            state["message"],
            runtime.context.timezone,
            context=_conversation_anchor(state, task),
        )
        if scope_error:
            errors.append(scope_error)

        if task != "study" and not scope.disciplines and not scope.lessons:
            return _with_errors(update, errors, state)

        overview = _wants_overview(state["message"])
        async with span(
            "graph.retrieve_context",
            "rag",
            task=task,
            lessons=len(scope.lessons),
            overview=overview,
        ) as observed:
            chunks: list[RetrievedChunk] = []
            # Pergunta de visao geral pula o top-k: "me ajuda com a descricao da
            # atividade" nao se parece com nenhum trecho da fala do professor, e
            # o que responde isso e a aula amostrada de ponta a ponta.
            if not (overview and scope.transcribed):
                try:
                    gateway = retrieval or _default_gateway()
                    chunks = await _search(gateway, state["message"], tenant_id, scope)
                except Exception as exc:
                    # Falha de indice nao pode calar a resposta: o modelo responde
                    # do que foi confirmado no banco, que e degradacao aceitavel.
                    observed.fail(exc)
                    errors.append(f"busca de aula falhou: {exc}")
            if not chunks and scope.transcribed:
                # A aula esta no banco - por indice atrasado ou por ser pedido
                # de visao geral, ler a transcricao responde melhor.
                try:
                    chunks = await _transcript_fallback(
                        scope, _OVERVIEW_LIMIT if overview else _STUDY_LIMIT
                    )
                except Exception as exc:
                    observed.fail(exc)
                    errors.append(f"leitura da transcricao falhou: {exc}")
            chunks = _summaries(scope) + chunks
            observed.set(chunks=len(chunks))

        from ...services.lesson_context_service import describe

        context = describe(scope) + format_context(chunks)
        if context:
            update["system_prompt"] = state["system_prompt"] + context
        return _with_errors(update, errors, state)

    return retrieve_context


def _with_errors(
    update: dict[str, Any],
    errors: list[str],
    state: ChatGraphState,
) -> dict[str, Any]:
    """Anexa as falhas nao fatais acumuladas, quando houver alguma nova."""
    if errors and errors != list(state.get("errors") or []):
        update["errors"] = errors
    return update


def _conversation_anchor(state: ChatGraphState, task: str) -> tuple[str, ...]:
    """Falas anteriores que podem carregar a disciplina e a data desta pergunta.

    So valem quando a mensagem atual e mesmo sobre aula: herdar a ancora numa
    pergunta de outro assunto colaria contexto de aula onde ele nao tem nada a
    fazer. Sao as falas do usuario - a do assistente costuma repetir varias
    disciplinas ao listar o catalogo, o que so atrapalha o casamento.
    """
    from ...services.lesson_context_service import is_follow_up

    if task != "study" and not is_follow_up(state["message"]):
        return ()
    history = state.get("history") or []
    return tuple(
        item.content
        for item in history
        if getattr(item, "role", "") == "user" and str(item.content or "").strip()
    )[-_CONTEXT_TURNS:]


def _wants_overview(message: str) -> bool:
    from ...services.lesson_context_service import wants_overview

    return wants_overview(message)


async def _scope(
    tenant_id: str,
    message: str,
    timezone_name: str,
    *,
    context: tuple[str, ...] = (),
) -> tuple["LessonScope", str]:
    """Confere disciplina, data e transcricao no banco relacional.

    A consulta e propositalmente tolerante: com o SQL indisponivel o RAG
    continua funcionando sem ancora, e a falha viaja no estado em vez de
    derrubar a conversa.
    """
    from ...core.database import AsyncSessionLocal
    from ...services import lesson_context_service

    try:
        async with AsyncSessionLocal() as db:
            scope = await lesson_context_service.resolve(
                db,
                tutor_id=tenant_id,
                message=message,
                context=context,
                timezone_name=timezone_name,
            )
        return scope, ""
    except Exception as exc:
        return lesson_context_service.LessonScope(), f"validacao de aula falhou: {exc}"


async def _transcript_fallback(
    scope: "LessonScope",
    limit: int = _STUDY_LIMIT,
) -> list[RetrievedChunk]:
    from ...core.database import AsyncSessionLocal
    from ...services import lesson_context_service

    async with AsyncSessionLocal() as db:
        return await lesson_context_service.transcript_chunks(db, scope, limit=limit)


def _summaries(scope: "LessonScope") -> list[RetrievedChunk]:
    from ...services.lesson_context_service import summary_chunks

    return summary_chunks(scope)[:_SUMMARY_LIMIT]


async def _search(
    retrieval: RetrievalGateway,
    message: str,
    tenant_id: str,
    scope: "LessonScope",
) -> list[RetrievedChunk]:
    """Busca com reindexacao de recuperacao, quando o gateway oferecer."""
    lesson_ids = scope.lesson_ids
    min_score = _ANCHORED_MIN_SCORE if lesson_ids else _STUDY_MIN_SCORE
    catch_up = getattr(retrieval, "search_with_catch_up", None)
    search = catch_up or retrieval.search
    return await search(
        message,
        tenant_id=tenant_id,
        limit=_STUDY_LIMIT,
        min_score=min_score,
        lesson_ids=lesson_ids,
    )


def _default_gateway() -> RetrievalGateway:
    """O gateway de busca do processo, resolvido no momento da chamada."""
    from ...adapters.container import get_retrieval_gateway

    return get_retrieval_gateway()
