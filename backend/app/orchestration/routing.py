"""Arestas condicionais do grafo do chat.

Isolar o roteamento em funcoes puras torna a decisao testavel sem rodar o grafo
inteiro: dado um estado, qual e a proxima aresta. E tambem deixa explicito onde
esta a regra que antes ficava escondida numa cadeia de `if` dentro do
orquestrador.
"""

from __future__ import annotations

from typing import cast

from ..orchestration.state import (
    ACTION_KINDS,
    ChatGraphState,
    GraphRoute,
)


def route_after_resolution(state: ChatGraphState) -> GraphRoute:
    """Escolhe o ramo depois que a acao e o contexto foram resolvidos.

    A precedencia e proposital: consulta de agenda e acao local tem resposta
    propria e ganham do modo de resposta pedido pelo usuario. So quando nada
    disso se aplica e que `single`, `multi` ou `chain` decidem.

    Args:
        state: estado apos `retrieve_context`.

    Returns:
        O nome do ramo a seguir.
    """
    action_kind = state.get("action_kind")
    if action_kind == "calendar_query":
        return "calendar_query"
    if action_kind in ACTION_KINDS:
        return "action"
    return cast(GraphRoute, state["mode"].value)
