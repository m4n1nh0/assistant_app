"""Leitura da configuracao de servidores MCP.

`MCP_SERVERS` e escrita a mao pelo usuario, entao o parser e deliberadamente
tolerante: aceita mapa e lista, deduz o transporte pelo formato e trata JSON
invalido como "nenhum servidor" em vez de erro fatal. Um assistente que se
recusa a subir porque uma integracao opcional esta mal escrita e pior que um
assistente sem aquela integracao.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class MCPServerConfig:
    """Um servidor MCP declarado na configuracao.

    Attributes:
        name: nome usado em log, trace e diagnostico.
        transport: `stdio` para processo local, `streamable_http` para servico.
        options: o restante da configuracao, repassado ao cliente MCP.
    """

    name: str
    transport: str
    options: dict[str, Any]

    def as_client_entry(self) -> dict[str, Any]:
        """Formato que o `MultiServerMCPClient` espera."""
        return {**self.options, "transport": self.transport}


def parse_servers(raw: str) -> dict[str, MCPServerConfig]:
    """Le `MCP_SERVERS`, aceitando tanto o mapa quanto a lista de servidores.

    Args:
        raw: conteudo cru da variavel de ambiente.

    Returns:
        Os servidores por nome. Configuracao ausente ou invalida devolve vazio.
    """
    text = (raw or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"MCP_SERVERS nao e JSON valido: {exc}")
        return {}

    if isinstance(parsed, list):
        collected: dict[str, Any] = {}
        for index, item in enumerate(parsed):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"mcp_{index}")
            collected[name] = {k: v for k, v in item.items() if k != "name"}
        parsed = collected

    if not isinstance(parsed, dict):
        logger.warning("MCP_SERVERS deve ser objeto ou lista de servidores")
        return {}

    servers: dict[str, MCPServerConfig] = {}
    for name, options in parsed.items():
        if not isinstance(options, dict):
            continue
        entry = dict(options)
        # O adaptador exige transport explicito; inferimos pelo formato para o
        # usuario nao precisar decorar o campo.
        transport = str(
            entry.pop("transport", "")
            or ("streamable_http" if entry.get("url") else "stdio")
        )
        servers[str(name)] = MCPServerConfig(
            name=str(name), transport=transport, options=entry
        )
    return servers


def as_client_config(servers: dict[str, MCPServerConfig]) -> dict[str, dict[str, Any]]:
    """Converte os servidores para o mapa que o cliente MCP consome."""
    return {name: config.as_client_entry() for name, config in servers.items()}
