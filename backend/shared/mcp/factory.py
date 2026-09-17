"""Construcao do cliente MCP a partir da configuracao.

Um lugar so decide timeout, retry, cache e disjuntor: a assistant-api (MCP
local) e o mcp-service chamam esta funcao, e por isso os dois se comportam igual
sob falha.
"""

from __future__ import annotations

from ..settings import MCPSettings, get_mcp_settings
from .client import MCPClient


def build_mcp_client(settings: MCPSettings | None = None) -> MCPClient:
    """Cria um `MCPClient` com os parametros de resiliencia configurados.

    Args:
        settings: configuracao a usar; `None` le a do processo. A API passa o
            proprio `Settings`, que herda de `MCPSettings`.
    """
    settings = settings or get_mcp_settings()
    return MCPClient(
        settings.mcp_servers,
        timeout_seconds=settings.mcp_timeout_seconds,
        max_retries=settings.mcp_max_retries,
        retry_backoff=settings.mcp_retry_backoff_seconds,
        cache_ttl_seconds=settings.mcp_tools_cache_ttl_seconds,
        failure_threshold=settings.mcp_circuit_failure_threshold,
        circuit_reset_seconds=settings.mcp_circuit_reset_seconds,
    )
