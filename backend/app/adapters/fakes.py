"""Implementacoes in-memory dos gateways, para teste e desenvolvimento.

Existem por causa da regra de inversao de dependencia: se o teste de um agente
precisa de um servidor MCP de pe ou do tool-service rodando, a inversao nao
aconteceu de verdade. Com estes fakes, o teste de agente exercita decisao,
roteamento e handoff sem nenhuma dependencia externa.

Eles tambem registram o que receberam, o que permite verificar *como* o agente
chamou a ferramenta - e nao so o que voltou.
"""

from __future__ import annotations

from typing import Any, Callable

from ..ports.mcp import MCPServerHealth, MCPToolRef, MCPUnavailable
from ..ports.tools import ToolDescriptor, ToolInvocation, ToolResult


class FakeToolGateway:
    """Catalogo em memoria que devolve respostas roteirizadas."""

    def __init__(
        self,
        descriptors: list[ToolDescriptor] | None = None,
        *,
        outputs: dict[str, Any] | None = None,
        failures: dict[str, str] | None = None,
    ) -> None:
        self._descriptors = list(descriptors or [])
        self._outputs = dict(outputs or {})
        self._failures = dict(failures or {})
        self.calls: list[ToolInvocation] = []

    def add(
        self,
        name: str,
        *,
        description: str = "ferramenta de teste",
        scopes: tuple[str, ...] = (),
        output: Any = "ok",
        source: str = "local",
        server: str = "",
    ) -> ToolDescriptor:
        """Publica uma ferramenta fake e devolve o descritor criado."""
        descriptor = ToolDescriptor(
            name=name,
            description=description,
            args_schema={"type": "object", "properties": {}},
            source=source,  # type: ignore[arg-type]
            server=server,
            scopes=scopes,
        )
        self._descriptors.append(descriptor)
        self._outputs[name] = output
        return descriptor

    def fail(self, name: str, error: str) -> None:
        """Faz uma ferramenta falhar na proxima chamada."""
        self._failures[name] = error

    async def list_tools(self, *, agent_id: str = "") -> list[ToolDescriptor]:
        """Ferramentas visiveis para um agente."""
        if not agent_id:
            return list(self._descriptors)
        return [item for item in self._descriptors if item.allowed_for(agent_id)]

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        """Registra a chamada e devolve a resposta roteirizada."""
        self.calls.append(invocation)
        known = {item.name for item in self._descriptors}
        if invocation.name not in known:
            return ToolResult(
                name=invocation.name,
                ok=False,
                error=f"ferramenta desconhecida: {invocation.name}",
            )
        if invocation.name in self._failures:
            return ToolResult(
                name=invocation.name,
                ok=False,
                error=self._failures[invocation.name],
            )
        return ToolResult(
            name=invocation.name,
            ok=True,
            output=self._outputs.get(invocation.name, "ok"),
        )

    async def health(self) -> dict[str, Any]:
        """Health estatico, sempre saudavel."""
        return {"ok": True, "transport": "fake", "tools": len(self._descriptors)}


class FakeMCPGateway:
    """Servidor MCP simulado, sem processo externo."""

    def __init__(
        self,
        tools: list[MCPToolRef] | None = None,
        *,
        handler: Callable[[str, dict[str, Any]], Any] | None = None,
        available: bool = True,
    ) -> None:
        self._tools = list(tools or [])
        self._handler = handler
        self._available = available
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def add(self, name: str, *, server: str = "fake", description: str = "") -> None:
        """Anuncia mais uma ferramenta MCP."""
        self._tools.append(
            MCPToolRef(
                name=name,
                server=server,
                description=description or f"{name} via MCP",
                args_schema={"type": "object", "properties": {}},
            )
        )

    def configured(self) -> bool:
        """Diz se ha servidor declarado."""
        return bool(self._tools) or self._available

    async def list_tools(self, *, force: bool = False) -> list[MCPToolRef]:
        """Ferramentas anunciadas; lista vazia quando indisponivel."""
        if not self._available:
            return []
        return list(self._tools)

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Executa a ferramenta simulada."""
        self.calls.append((name, dict(args)))
        if not self._available:
            raise MCPUnavailable("servidor MCP fake indisponivel")
        if self._handler is not None:
            return self._handler(name, args)
        return f"{name} executada"

    async def health(self) -> list[MCPServerHealth]:
        """Estado dos servidores simulados."""
        return [
            MCPServerHealth(
                name="fake",
                transport="stdio",
                reachable=self._available,
                tools=len(self._tools),
            )
        ]
