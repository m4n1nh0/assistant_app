"""Tool Gateway in-process: o catalogo roda dentro do backend.

E o modo padrao. As ferramentas de acao deste projeto so **montam proposta** -
quem executa e a interface, apos confirmacao do usuario - entao nao ha efeito
colateral a isolar em outro processo, e um salto de rede so acrescentaria
latencia ao caminho mais comum.

A governanca nao depende do transporte: o mesmo registry e o mesmo executor
rodam aqui e dentro do tool-service. Trocar para o gateway remoto e configuracao,
nao reescrita.
"""

from __future__ import annotations

from typing import Any

from ...ports.mcp import MCPGateway
from ...ports.tools import ToolDescriptor, ToolInvocation, ToolResult
from ...toolkit.catalog import sync_mcp_tools
from ...toolkit.executor import ToolExecutor
from ...toolkit.registry import ToolRegistry
from ...services.device_catalog_service import DeviceCatalog, get_device_catalog


class LocalToolGateway:
    """Implementa `ToolGateway` sobre o catalogo do proprio processo."""

    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        *,
        mcp: MCPGateway | None = None,
        mcp_timeout_seconds: float | None = None,
        devices: "DeviceCatalog | None" = None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._mcp = mcp
        self._mcp_timeout = mcp_timeout_seconds
        self._devices = devices if devices is not None else get_device_catalog()

    @property
    def registry(self) -> ToolRegistry:
        """O catalogo por tras deste gateway."""
        return self._registry

    async def list_tools(self, *, agent_id: str = "") -> list[ToolDescriptor]:
        """Ferramentas visiveis para um agente, ja com as capacidades MCP.

        A sincronizacao com o MCP acontece aqui, e nao na subida do processo:
        servidor MCP pode entrar e sair a qualquer momento, e o cache do proprio
        gateway MCP e quem controla a frequencia de reconsulta.

        As capacidades da maquina do usuario entram por cima, vindas do catalogo
        daquele dispositivo - nunca do catalogo do processo, para uma sessao nao
        enxergar a maquina de outra.
        """
        await self._refresh_mcp(agent_id)
        tools = self._registry.descriptors(agent_id=agent_id)
        return tools + self._devices.descriptors(agent_id=agent_id)

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        """Executa uma ferramenta pelo executor governado.

        Capacidade da maquina do usuario roda pelo executor daquele dispositivo,
        que so alcanca o catalogo dele.
        """
        device_executor = self._devices.executor()
        if device_executor is not None and self._devices.find(invocation.name):
            return await device_executor.invoke(invocation)
        return await self._executor.invoke(invocation)

    async def health(self) -> dict[str, Any]:
        """Tamanho do catalogo por origem, para diagnostico."""
        descriptors = self._registry.descriptors()
        by_source: dict[str, int] = {}
        for descriptor in descriptors:
            by_source[descriptor.source] = by_source.get(descriptor.source, 0) + 1
        return {
            "ok": True,
            "transport": "local",
            "tools": len(descriptors),
            "by_source": by_source,
            "mcp_attached": self._mcp is not None and self._mcp.configured(),
            "devices": len(self._devices),
        }

    async def _refresh_mcp(self, agent_id: str) -> None:
        if self._mcp is None:
            return
        # So paga a sincronizacao quando o agente pode usar capacidade MCP:
        # o agente de estudos nunca vai ver essas ferramentas, entao consultar
        # servidor por causa dele seria latencia sem retorno.
        from ...orchestration.agents import mcp_scopes

        if agent_id and agent_id not in mcp_scopes():
            return
        await sync_mcp_tools(
            self._registry, self._mcp, timeout_seconds=self._mcp_timeout
        )
