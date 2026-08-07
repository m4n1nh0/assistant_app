"""Conecta servidores MCP e expoe as ferramentas deles ao grafo.

Servidores MCP sao processos externos: podem estar fora do ar, demorar para
subir ou nem existir na maquina. Nada aqui pode derrubar o chat — na falha, o
assistente simplesmente responde sem aquelas ferramentas.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.tools import BaseTool
from loguru import logger

from ..core.config import get_settings

settings = get_settings()

_CACHE_TTL_SECONDS = 300.0
_cache: tuple[float, list[BaseTool]] | None = None
_last_error: str = ""


def _parse_servers() -> dict[str, dict[str, Any]]:
    """Le MCP_SERVERS, aceitando tanto o mapa quanto a lista de servidores."""
    raw = settings.mcp_servers.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"MCP_SERVERS nao e JSON valido: {e}")
        return {}

    if isinstance(parsed, list):
        servers = {}
        for index, item in enumerate(parsed):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"mcp_{index}")
            config = {k: v for k, v in item.items() if k != "name"}
            servers[name] = config
        parsed = servers

    if not isinstance(parsed, dict):
        logger.warning("MCP_SERVERS deve ser objeto ou lista de servidores")
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for name, config in parsed.items():
        if not isinstance(config, dict):
            continue
        entry = dict(config)
        # O adaptador exige transport explicito; inferimos pelo formato para o
        # usuario nao precisar decorar o campo.
        if "transport" not in entry:
            entry["transport"] = "streamable_http" if entry.get("url") else "stdio"
        normalized[str(name)] = entry
    return normalized


def configured() -> bool:
    return bool(_parse_servers())


async def get_tools(*, force: bool = False) -> list[BaseTool]:
    """Ferramentas de todos os servidores MCP configurados."""
    global _cache, _last_error

    servers = _parse_servers()
    if not servers:
        return []

    now = time.monotonic()
    if not force and _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return list(_cache[1])

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as e:
        _last_error = f"langchain-mcp-adapters ausente: {e}"
        logger.warning(_last_error)
        return []

    try:
        client = MultiServerMCPClient(servers)
        tools = await client.get_tools()
    except Exception as e:
        _last_error = str(e)
        logger.warning(f"Servidores MCP indisponiveis: {e}")
        # Guarda a falha no cache para nao tentar reconectar a cada mensagem.
        _cache = (now, [])
        return []

    _last_error = ""
    _cache = (now, list(tools))
    logger.info(
        f"MCP conectado: {len(tools)} ferramentas de "
        f"{len(servers)} servidor(es)"
    )
    return list(tools)


async def status() -> dict[str, Any]:
    servers = _parse_servers()
    if not servers:
        return {"configured": False, "servers": [], "tools": 0}

    tools = await get_tools()
    return {
        "configured": True,
        "servers": sorted(servers),
        "tools": len(tools),
        "tool_names": sorted(tool.name for tool in tools),
        "error": _last_error or None,
    }


def reset_cache() -> None:
    global _cache, _last_error
    _cache = None
    _last_error = ""
