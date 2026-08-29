"""mcp-service: os servidores MCP em processo proprio.

Este e o servico cuja extracao se paga. Servidor MCP com transporte `stdio` sobe
**subprocesso** na maquina - `npx`, um binario, um script. Um servidor que trava,
vaza memoria ou morre nao pode levar o backend junto, e precisa poder ser
reiniciado sozinho.

O contrato e pequeno de proposito: listar servidores, listar capacidades,
executar uma capacidade. Ele nao sabe o que e agente, especialista ou tool
calling - quem transforma capacidade em ferramenta do assistente e o Tool
Service, do outro lado do `MCPGateway`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, Query
from loguru import logger

from app.adapters.container import build_mcp_client
from app.core.config import get_settings
from app.ports.mcp import MCPUnavailable

from ..common import create_service, serve

settings = get_settings()
client = build_mcp_client()


async def _ready() -> dict[str, Any]:
    """Pronto quando ha servidor configurado e alcancavel.

    Sem servidor declarado o servico esta pronto e vazio: e uma instalacao que
    simplesmente nao usa MCP, e nao uma falha.
    """
    if not client.configured():
        return {"ok": True, "configured": False, "servers": 0}
    health = await client.health()
    reachable = [item for item in health if item.reachable]
    return {
        "ok": bool(reachable),
        "configured": True,
        "servers": len(health),
        "reachable": len(reachable),
        "error": client.last_error or None,
    }


async def _startup() -> None:
    if not client.configured():
        logger.info("mcp-service sem servidores declarados em MCP_SERVERS")
        return
    tools = await client.list_tools()
    logger.info(
        f"mcp-service pronto: {len(tools)} capacidades de "
        f"{len(client.server_names())} servidor(es)"
    )


app = create_service(
    name="mcp-service",
    title="MCP Service",
    description=(
        "Interoperabilidade com capacidades externas via Model Context "
        "Protocol. Ciclo de vida, resiliencia e diagnostico dos servidores MCP."
    ),
    ready_check=_ready,
    on_startup=_startup,
)


@app.get("/mcp/servers")
async def list_servers() -> dict[str, Any]:
    """Estado de cada servidor MCP configurado."""
    health = await client.health()
    return {
        "configured": client.configured(),
        "servers": [
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


@app.get("/mcp/tools")
async def list_tools(
    force: bool = Query(False, description="ignora o cache e reconsulta"),
) -> dict[str, Any]:
    """Capacidades anunciadas pelos servidores configurados."""
    refs = await client.list_tools(force=force)
    return {
        "configured": client.configured(),
        "tools": [
            {
                "name": ref.name,
                "server": ref.server,
                "description": ref.description,
                "args_schema": ref.args_schema,
            }
            for ref in refs
        ],
    }


@app.post("/mcp/tools/{name}/invoke")
async def invoke_tool(name: str, body: dict[str, Any] = Body(default={})):
    """Executa uma capacidade MCP.

    Falha vira `ok=False` com o motivo, e nao erro HTTP: o cliente precisa
    devolver a explicacao ao modelo e seguir a conversa, o que um `500`
    transformaria em excecao no meio da resposta.
    """
    args = body.get("args") or {}
    timeout = body.get("timeout_seconds")
    try:
        output = await client.invoke(name, args, timeout_seconds=timeout)
    except MCPUnavailable as exc:
        return {"ok": False, "name": name, "error": str(exc)}
    except Exception as exc:
        logger.warning(f"mcp-service: {name} falhou: {exc}")
        return {"ok": False, "name": name, "error": str(exc)}
    return {"ok": True, "name": name, "output": output}


@app.post("/mcp/reset")
async def reset_cache() -> dict[str, Any]:
    """Descarta o cache e fecha o disjuntor, forcando reconexao."""
    client.reset()
    return {"ok": True}


def main() -> None:
    """Sobe o mcp-service na porta configurada."""
    serve("services.mcp_service.main:app", port=settings.mcp_service_port)


if __name__ == "__main__":
    main()
