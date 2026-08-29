"""MCP Gateway in-process: o cliente MCP roda dentro do backend.

Modo padrao do desenvolvimento local. Serve tambem como implementacao de
referencia do contrato: o gateway remoto precisa devolver exatamente estes
tipos, e os testes de contrato comparam os dois.
"""

from __future__ import annotations

from typing import Any

from ...mcp.client import MCPClient
from ...ports.mcp import MCPServerHealth, MCPToolRef


class LocalMCPGateway:
    """Implementa `MCPGateway` sobre o `MCPClient` deste processo."""

    def __init__(self, client: MCPClient) -> None:
        self._client = client

    @property
    def client(self) -> MCPClient:
        """O cliente por tras deste gateway."""
        return self._client

    def configured(self) -> bool:
        """Diz se ha ao menos um servidor MCP declarado."""
        return self._client.configured()

    async def list_tools(self, *, force: bool = False) -> list[MCPToolRef]:
        """Ferramentas anunciadas pelos servidores configurados."""
        return await self._client.list_tools(force=force)

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Executa uma ferramenta MCP pelo nome."""
        return await self._client.invoke(
            name, args, timeout_seconds=timeout_seconds
        )

    async def health(self) -> list[MCPServerHealth]:
        """Estado de cada servidor configurado."""
        return await self._client.health()
