"""Montagem do catalogo: ferramentas locais e capacidades vindas de MCP.

Aqui fica a unica traducao entre `BaseTool` do LangChain e o contrato proprio
`ToolDescriptor`. O resto da aplicacao trabalha com o contrato; o LangChain
entra so onde ele e util, que e descrever e validar argumento.

O ponto arquitetural importante esta em `sync_mcp_tools`: uma capacidade MCP
vira **uma entrada do catalogo com origem `mcp`**, cujo executor delega ao
`MCPGateway`. Isso mantem MCP como protocolo e Tool Calling como mecanismo -
o agente dispara do mesmo jeito, a auditoria registra de onde veio, e trocar o
transporte MCP nao mexe em nenhum agente.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.tools import BaseTool
from loguru import logger

from ..orchestration.agents import mcp_scopes, scopes_for_tool
from ..ports.mcp import MCPGateway
from ..ports.tools import ToolDescriptor, ToolSource
from .registry import ToolRegistry, ToolRunner


def descriptor_from_langchain(
    tool: BaseTool,
    *,
    source: ToolSource = "local",
    server: str = "",
    scopes: tuple[str, ...] = (),
    timeout_seconds: float | None = None,
    read_only: bool = True,
) -> ToolDescriptor:
    """Converte uma tool do LangChain no contrato publico do catalogo."""
    return ToolDescriptor(
        name=tool.name,
        description=tool.description or "",
        args_schema=_json_schema(tool),
        source=source,
        server=server,
        scopes=scopes,
        timeout_seconds=timeout_seconds,
        read_only=read_only,
    )


def runner_from_langchain(tool: BaseTool) -> ToolRunner:
    """Executor que chama a tool do LangChain de forma assincrona."""

    async def _run(args: dict[str, Any]) -> Any:
        return await tool.ainvoke(args)

    return _run


def register_langchain_tools(
    registry: ToolRegistry,
    tools: Sequence[BaseTool],
    *,
    source: ToolSource = "local",
    server: str = "",
    scopes: tuple[str, ...] | None = None,
    timeout_seconds: float | None = None,
) -> int:
    """Publica um conjunto de tools do LangChain no catalogo.

    Args:
        registry: catalogo de destino.
        tools: tools a registrar.
        source: origem a gravar no descritor.
        server: servidor de origem, quando houver.
        scopes: escopo fixo; `None` deduz o escopo de cada ferramenta pelos
            especialistas que a declaram.
        timeout_seconds: teto proprio destas ferramentas.

    Returns:
        Quantas ferramentas foram registradas.
    """
    count = 0
    for tool in tools:
        resolved = scopes if scopes is not None else scopes_for_tool(tool.name)
        registry.register(
            descriptor_from_langchain(
                tool,
                source=source,
                server=server,
                scopes=resolved,
                timeout_seconds=timeout_seconds,
            ),
            runner_from_langchain(tool),
        )
        count += 1
    return count


def build_local_registry() -> ToolRegistry:
    """Catalogo com as ferramentas de acao locais do assistente.

    O escopo de cada uma sai da declaracao dos especialistas, entao liberar uma
    ferramenta para um agente novo e mexer em um lugar so.
    """
    from ..services.assistant_tools import ASSISTANT_TOOLS

    registry = ToolRegistry()
    register_langchain_tools(registry, ASSISTANT_TOOLS)
    logger.debug(f"Catalogo local com {len(registry)} ferramentas")
    return registry


async def sync_mcp_tools(
    registry: ToolRegistry,
    gateway: MCPGateway,
    *,
    force: bool = False,
    timeout_seconds: float | None = None,
) -> int:
    """Espelha as capacidades MCP no catalogo, como ferramentas de origem `mcp`.

    Servidor fora do ar nao esvazia o catalogo: mantemos o que ja estava
    registrado e seguimos. Derrubar as capacidades a cada oscilacao de rede
    trocaria uma falha temporaria por uma mudanca de comportamento do agente.

    Args:
        registry: catalogo de destino.
        gateway: porta de acesso ao MCP.
        force: ignora o cache do gateway e reconsulta os servidores.
        timeout_seconds: teto por chamada de ferramenta MCP.

    Returns:
        Quantas capacidades MCP ficaram publicadas.
    """
    if not gateway.configured():
        registry.unregister_source("mcp")
        return 0

    try:
        refs = await gateway.list_tools(force=force)
    except Exception as exc:
        logger.warning(f"Catalogo MCP nao atualizado: {exc}")
        return len(registry.descriptors(source="mcp"))

    if not refs:
        return len(registry.descriptors(source="mcp"))

    scopes = mcp_scopes()
    fresh = {ref.name for ref in refs}
    for ref in refs:
        registry.register(
            ToolDescriptor(
                name=ref.name,
                description=ref.description,
                args_schema=ref.args_schema,
                source="mcp",
                server=ref.server,
                scopes=scopes,
                timeout_seconds=timeout_seconds,
                read_only=False,
            ),
            _mcp_runner(gateway, ref.name, timeout_seconds),
        )

    for descriptor in registry.descriptors(source="mcp"):
        if descriptor.name not in fresh:
            registry.unregister(descriptor.name)
    return len(fresh)


def _mcp_runner(
    gateway: MCPGateway,
    name: str,
    timeout_seconds: float | None,
) -> ToolRunner:
    async def _run(args: dict[str, Any]) -> Any:
        return await gateway.invoke(name, args, timeout_seconds=timeout_seconds)

    return _run


def _json_schema(tool: BaseTool) -> dict[str, Any]:
    """JSON Schema dos argumentos, tolerante a tool sem schema declarado."""
    try:
        schema = tool.args_schema
        if schema is None:
            return {"type": "object", "properties": tool.args or {}}
        if isinstance(schema, dict):
            return dict(schema)
        return schema.model_json_schema()
    except Exception:
        return {"type": "object", "properties": {}}
