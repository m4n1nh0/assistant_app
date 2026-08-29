"""tool-service: o catalogo de ferramentas em processo proprio.

Roda o **mesmo** registry e o **mesmo** executor que o modo in-process usa. Isso
nao e coincidencia: e o que garante que mover o catalogo para fora nao muda
regra de autorizacao, timeout, retry nem auditoria. O que muda e so o
transporte.

Por padrao a aplicacao nao sobe este servico. As ferramentas deste projeto
apenas **montam proposta** - quem executa e a interface, apos confirmacao do
usuario - entao nao ha efeito colateral a isolar, e o salto de rede seria
latencia pura no caminho mais comum. O servico existe para quando isso deixar
de ser verdade: ferramenta com efeito real, catalogo compartilhado entre varias
aplicacoes, ou necessidade de limitar recurso por ferramenta.
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, Query
from loguru import logger

from app.adapters.container import build_local_tool_gateway
from app.core.config import get_settings
from app.ports.tools import ToolInvocation

from ..common import create_service, serve

settings = get_settings()
gateway = build_local_tool_gateway()


async def _ready() -> dict[str, Any]:
    """Pronto quando o catalogo tem ao menos uma ferramenta publicada."""
    health = await gateway.health()
    tools = int(health.get("tools") or 0)
    return {"ok": tools > 0, **health}


async def _startup() -> None:
    descriptors = await gateway.list_tools()
    logger.info(f"tool-service pronto: {len(descriptors)} ferramentas")


app = create_service(
    name="tool-service",
    title="Tool Service",
    description=(
        "Catalogo, governanca e execucao das ferramentas. Concentra descoberta, "
        "escopo por agente, validacao, timeout, retry e auditoria."
    ),
    ready_check=_ready,
    on_startup=_startup,
)


@app.get("/tools")
async def list_tools(
    agent_id: str = Query("", description="filtra pelo escopo de um agente"),
) -> dict[str, Any]:
    """Catalogo visivel, opcionalmente filtrado pelo escopo de um agente."""
    descriptors = await gateway.list_tools(agent_id=agent_id)
    return {
        "agent_id": agent_id,
        "tools": [
            {
                "name": item.name,
                "description": item.description,
                "args_schema": item.args_schema,
                "source": item.source,
                "server": item.server,
                "scopes": list(item.scopes),
                "timeout_seconds": item.timeout_seconds,
                "read_only": item.read_only,
            }
            for item in descriptors
        ],
    }


@app.post("/tools/{name}/invoke")
async def invoke_tool(name: str, body: dict[str, Any] = Body(default={})):
    """Executa uma ferramenta do catalogo.

    O resultado sai sempre normalizado, inclusive na falha: o cliente precisa
    devolver ao modelo um texto que ele consiga contornar, e nao um erro HTTP
    que interromperia a resposta.
    """
    result = await gateway.invoke(
        ToolInvocation(
            name=name,
            args=body.get("args") or {},
            agent_id=str(body.get("agent_id") or ""),
            timeout_seconds=body.get("timeout_seconds"),
            call_id=str(body.get("call_id") or ""),
        )
    )
    return {
        "ok": result.ok,
        "name": result.name,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "source": result.source,
        "retries": result.retries,
    }


def main() -> None:
    """Sobe o tool-service na porta configurada."""
    serve("services.tool_service.main:app", port=settings.tool_service_port)


if __name__ == "__main__":
    main()
