"""Fachada de diagnostico do MCP para as rotas da aplicacao.

A implementacao mora em `app.mcp` (conexao, cache, resiliencia) e chega ao resto
do sistema por `app.ports.mcp.MCPGateway`. Este modulo existe so para a camada
de rotas: ela precisa de um resumo pronto para a tela de status, e nao do
contrato completo.

O que mudou em relacao a versao anterior deste arquivo e importante: nenhum
agente ou no de grafo importa daqui. Eles falam com o Tool Gateway, que por sua
vez publica as capacidades MCP no catalogo. MCP voltou a ser protocolo, e nao
mecanismo de tool calling.
"""

from __future__ import annotations

from typing import Any

from ..adapters.container import get_mcp_gateway
from ..core.config import get_settings
from ..mcp.config import parse_servers


def configured() -> bool:
    """Diz se ha servidor MCP declarado em `MCP_SERVERS`."""
    return bool(parse_servers(get_settings().mcp_servers))


async def status() -> dict[str, Any]:
    """Estado de cada servidor MCP configurado, para diagnostico na interface."""
    gateway = get_mcp_gateway()
    if not gateway.configured():
        return {"configured": False, "servers": [], "tools": 0}

    health = await gateway.health()
    tools = await gateway.list_tools()
    errors = [item.error for item in health if item.error]
    return {
        "configured": True,
        "servers": sorted(item.name for item in health),
        "tools": len(tools),
        "tool_names": sorted(tool.name for tool in tools),
        "error": errors[0] if errors else None,
        "transport": "remote" if get_settings().uses_remote_mcp else "local",
        "detail": [
            {
                "name": item.name,
                "transport": item.transport,
                "reachable": item.reachable,
                "tools": item.tools,
                "error": item.error,
                "circuit_open": item.circuit_open,
            }
            for item in health
        ],
    }


def reset_cache() -> None:
    """Descarta o cache de capacidades, forcando reconexao na proxima chamada."""
    from ..adapters.container import reset

    gateway = get_mcp_gateway()
    client = getattr(gateway, "client", None)
    if client is not None:
        client.reset()
    else:
        reset()
