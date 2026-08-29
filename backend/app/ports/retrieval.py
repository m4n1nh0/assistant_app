"""Contrato de RAG: buscar trecho relevante sem dizer de onde ele vem.

Hoje a busca e no Qdrant com embedding proprio; amanha pode ser outro vector
store ou um retriever hibrido. Quem monta o prompt so precisa de trechos com
score e procedencia.

O `tenant_id` e obrigatorio de proposito: a colecao e compartilhada entre contas
e o isolamento e feito no filtro. Deixa-lo opcional convidaria a um vazamento
entre usuarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RetrievedChunk:
    """Um trecho recuperado, com o que basta para citar a fonte."""

    content: str
    score: float = 0.0
    source: str = ""
    reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class RetrievalGateway(Protocol):
    """Busca semantica sobre o material do usuario."""

    async def search(
        self,
        query: str,
        *,
        tenant_id: str,
        limit: int = 6,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """Trechos mais proximos da pergunta, ja filtrados por score."""
        ...
