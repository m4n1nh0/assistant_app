"""Orquestracao in-process: o grafo roda dentro da assistant-api.

A maquina da sessao ja esta amarrada pela rota (HTTP ou WebSocket) e as chaves
do usuario ja estao no `ContextVar`, entao aqui nao ha nada a transportar - so a
chamada ao grafo.
"""

from __future__ import annotations

from typing import Any

from ...core.config import get_settings
from ...ports.orchestration import ChatTurn


class LocalOrchestrationGateway:
    """Implementa `OrchestrationGateway` chamando o grafo do proprio processo."""

    async def run_chat(self, turn: ChatTurn) -> dict[str, Any]:
        """Roda o grafo compilado neste processo."""
        from ...orchestration.graph import run_chat_graph

        return await run_chat_graph(**turn.graph_kwargs())

    async def health(self) -> dict[str, Any]:
        """O grafo local esta sempre disponivel enquanto o processo estiver."""
        return {
            "ok": True,
            "transport": "local",
            "checkpointing": get_settings().checkpoint_backend,
        }
