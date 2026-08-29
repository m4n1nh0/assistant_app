"""RAG das aulas gravadas, atras de um contrato proprio.

Antes, a recuperacao era uma funcao privada dentro do servico de educacao: quem
quisesse usar o mesmo material em outro fluxo teria que duplicar a busca, e
trocar de vector store significaria mexer em regra de negocio. Agora e um
`RetrievalGateway`, consumido tanto pelo no de RAG do grafo quanto pelo modo
educacao.

Sobre nao usar `BaseRetriever` do LangChain aqui: a interface dele nao tem onde
carregar o dono dos dados, e este contrato exige `tenant_id` em toda busca. A
colecao e compartilhada entre contas e o isolamento e feito no filtro - deixar
esse campo fora da assinatura seria convidar um vazamento entre usuarios para
ganhar compatibilidade com cadeias que o projeto nao usa.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from ...core.observability import span
from ...ports.retrieval import RetrievedChunk


class LessonRetrievalGateway:
    """Busca semantica nas transcricoes de aula do usuario."""

    async def search(
        self,
        query: str,
        *,
        tenant_id: str,
        limit: int = 6,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """Trechos de aula mais proximos da pergunta.

        Falha de infraestrutura devolve lista vazia em vez de excecao: sem aula
        indexada o assistente responde do conhecimento geral, que e degradacao
        aceitavel; derrubar a conversa nao e.

        Args:
            query: pergunta em linguagem natural.
            tenant_id: perfil dono das aulas.
            limit: maximo de trechos.
            min_score: corte de similaridade.

        Returns:
            Os trechos relevantes, ja filtrados por score.
        """
        if not tenant_id or not query.strip():
            return []

        from ...services import qdrant_service

        async with span(
            "rag.lesson_search", "rag", limit=limit, min_score=min_score
        ) as observed:
            try:
                hits = await qdrant_service.search_lesson_transcripts(
                    tutor_id=tenant_id,
                    query=query,
                    limit=limit,
                )
            except Exception as exc:
                observed.fail(exc)
                logger.warning(f"Busca de contexto de aula falhou: {exc}")
                return []
            chunks = [
                _chunk(hit) for hit in hits if hit.get("score", 0.0) >= min_score
            ]
            observed.set(retrieved=len(hits), kept=len(chunks))
        return chunks

    async def search_with_catch_up(
        self,
        query: str,
        *,
        tenant_id: str,
        limit: int = 6,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """Busca e, se nao achar nada, reindexa uma vez antes de desistir.

        A aula pode existir no banco e faltar no indice - o Qdrant estava fora
        do ar na gravacao, ou o modelo de embedding mudou. A reindexacao tem
        intervalo minimo proprio, para pergunta sem resposta nao virar
        reindexacao em loop.
        """
        found = await self.search(
            query, tenant_id=tenant_id, limit=limit, min_score=min_score
        )
        if found:
            return found

        from ...services import lesson_index_service

        outcome = await lesson_index_service.catch_up(
            tutor_id=tenant_id, reason="busca de aula sem resultado"
        )
        if not outcome.get("indexed"):
            return []
        return await self.search(
            query, tenant_id=tenant_id, limit=limit, min_score=min_score
        )


def _chunk(hit: dict[str, Any]) -> RetrievedChunk:
    discipline = str(hit.get("discipline") or "aula")
    date = str(hit.get("lesson_date") or "")
    return RetrievedChunk(
        content=str(hit.get("content") or "").strip(),
        score=float(hit.get("score") or 0.0),
        source=discipline,
        reference=f"{discipline}, {date}" if date else discipline,
        metadata={
            "lesson_id": hit.get("lesson_id", ""),
            "lesson_date": date,
            "sequence": hit.get("sequence", 0),
        },
    )
