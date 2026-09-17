"""Contrato do MCP: interoperabilidade com capacidades externas.

MCP e **protocolo**, nao mecanismo de escolha de ferramenta. O que ele resolve e
falar com sistemas de fora - servidores que expoem ferramentas, recursos e
prompts - de forma padronizada, sem que a aplicacao conheca cada um.

Manter este contrato separado de `ports.tools` e proposital: o dia em que uma
capacidade MCP for consumida fora do fluxo de tool calling (um recurso lido
direto, por exemplo), o contrato ja existe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class MCPToolRef:
    """Uma ferramenta anunciada por um servidor MCP."""

    name: str
    server: str
    description: str = ""
    args_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPServerHealth:
    """Estado de um servidor MCP configurado.

    Attributes:
        name: nome dado ao servidor na configuracao.
        transport: stdio ou streamable_http.
        reachable: se a ultima tentativa de conexao funcionou.
        tools: quantas ferramentas ele anunciou.
        error: motivo da ultima falha.
        circuit_open: True quando o disjuntor esta cortando as tentativas.
    """

    name: str
    transport: str = ""
    reachable: bool = False
    tools: int = 0
    error: str = ""
    circuit_open: bool = False


class MCPError(Exception):
    """Falha ao falar com um servidor MCP."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class MCPUnavailable(MCPError):
    """Nenhum servidor MCP respondeu; o assistente segue sem essas capacidades."""


@runtime_checkable
class MCPGateway(Protocol):
    """Como o dominio fala com o MCP, in-process ou pelo mcp-service."""

    def configured(self) -> bool:
        """Diz se ha ao menos um servidor MCP declarado."""
        ...

    async def list_tools(self, *, force: bool = False) -> list[MCPToolRef]:
        """Ferramentas anunciadas por todos os servidores configurados."""
        ...

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Executa uma ferramenta MCP e devolve a saida crua do servidor."""
        ...

    async def health(self) -> list[MCPServerHealth]:
        """Estado de cada servidor configurado."""
        ...
