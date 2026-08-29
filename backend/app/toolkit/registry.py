"""Catalogo de ferramentas: quem existe, quem pode usar e como executar.

O registry e a fronteira de governanca do Tool Calling. Sem ele, cada agente
montava sua propria lista e a mesma capacidade acabava reimplementada em dois
lugares - e ninguem conseguia responder "quais ferramentas este agente pode
disparar" sem ler codigo.

Uma ferramenta registrada guarda duas coisas separadas de proposito: o
`ToolDescriptor`, que e o contrato publico (nome, schema, escopo, origem), e o
`runner`, que e o codigo. Quem consulta o catalogo ve so o contrato.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..ports.tools import ToolDescriptor, ToolSource

ToolRunner = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class RegisteredTool:
    """Um item do catalogo: o contrato publico e o codigo que o cumpre."""

    descriptor: ToolDescriptor
    runner: ToolRunner


class ToolRegistry:
    """Catalogo em memoria, seguro para uso concorrente.

    Registro por origem (`local`, `mcp`, `remote`) permite recarregar so o que
    veio de fora sem derrubar as ferramentas locais - e o que torna a
    reconexao a um servidor MCP uma operacao barata.
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._lock = threading.RLock()

    def register(
        self,
        descriptor: ToolDescriptor,
        runner: ToolRunner,
        *,
        replace: bool = True,
    ) -> None:
        """Publica uma ferramenta no catalogo.

        Args:
            descriptor: contrato publico da ferramenta.
            runner: corrotina que recebe os argumentos e devolve a saida.
            replace: quando `False`, mantem o registro anterior de mesmo nome.
        """
        with self._lock:
            if not replace and descriptor.name in self._tools:
                return
            self._tools[descriptor.name] = RegisteredTool(descriptor, runner)

    def unregister(self, name: str) -> None:
        """Remove uma ferramenta pelo nome."""
        with self._lock:
            self._tools.pop(name, None)

    def unregister_source(self, source: ToolSource, *, server: str = "") -> int:
        """Remove todas as ferramentas de uma origem.

        Args:
            source: origem a limpar.
            server: limita a um servidor especifico dentro da origem.

        Returns:
            Quantas ferramentas foram removidas.
        """
        with self._lock:
            doomed = [
                name
                for name, item in self._tools.items()
                if item.descriptor.source == source
                and (not server or item.descriptor.server == server)
            ]
            for name in doomed:
                self._tools.pop(name, None)
            return len(doomed)

    def get(self, name: str) -> RegisteredTool | None:
        """A ferramenta registrada com aquele nome, se existir."""
        with self._lock:
            return self._tools.get(name)

    def descriptors(
        self,
        *,
        agent_id: str = "",
        source: ToolSource | None = None,
    ) -> list[ToolDescriptor]:
        """Contratos visiveis, ja filtrados por escopo e origem.

        Args:
            agent_id: quando informado, devolve so o que aquele agente pode usar.
            source: restringe a uma origem.

        Returns:
            Os descritores em ordem estavel de nome, para que o prompt do modelo
            nao mude a cada requisicao sem motivo.
        """
        with self._lock:
            items = [item.descriptor for item in self._tools.values()]
        if source is not None:
            items = [item for item in items if item.source == source]
        if agent_id:
            items = [item for item in items if item.allowed_for(agent_id)]
        return sorted(items, key=lambda item: item.name)

    def names(self) -> set[str]:
        """Nomes de tudo que esta registrado."""
        with self._lock:
            return set(self._tools)

    def clear(self) -> None:
        """Esvazia o catalogo. Usado nos testes."""
        with self._lock:
            self._tools.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._tools)
