"""Endpoints de diagnostico: armazenamento, agentes e servidores MCP.

Alimentam a tela de status da interface. Servico externo fora do ar aparece como
indisponivel na resposta, e nao como erro da rota.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import get_db
from ..core.security import get_current_user
from ..adapters.container import get_tool_gateway
from ..services import agent_service, embedding_service, mcp_service, qdrant_service

router = APIRouter(prefix="/system", tags=["System"], dependencies=[Depends(get_current_user)])
settings = get_settings()


@router.get("/storage/status")
async def storage_status(db: AsyncSession = Depends(get_db)):
    """Diagnostico de armazenamento: banco, Qdrant e provedor de embedding."""
    database = {
        "ok": False,
        "url": settings.database_url.split("@")[-1],
    }
    try:
        await db.execute(text("SELECT 1"))
        database["ok"] = True
    except Exception as e:
        database["error"] = str(e)

    return {
        "database": database,
        "qdrant": qdrant_service.status(),
    }


@router.get("/agents/status")
async def agents_status():
    """Quem pode atender, com que ferramentas e com quais embeddings.

    As ferramentas de cada especialista sao lidas do Tool Gateway, e nao da
    declaracao do agente: o que a tela mostra e o catalogo efetivo, ja com as
    capacidades MCP e ja filtrado por escopo. Ler da declaracao mostraria a
    intencao, e nao o que o agente realmente pode disparar.
    """
    gateway = get_tool_gateway()

    async def _tools_of(agent_id: str) -> list[dict]:
        try:
            descriptors = await gateway.list_tools(agent_id=agent_id)
        except Exception as exc:
            return [{"name": "", "error": str(exc)}]
        return [
            {"name": item.name, "source": item.source, "server": item.server}
            for item in descriptors
        ]

    specialists = []
    for item in agent_service.SPECIALISTS.values():
        specialists.append({
            "id": item.id,
            "label": item.label,
            "description": item.description,
            "routing_task": item.routing_task,
            "declared_tools": list(item.tool_names),
            "tools": await _tools_of(item.id),
            "uses_mcp": item.use_mcp,
        })

    try:
        tool_health = await gateway.health()
    except Exception as exc:
        tool_health = {"ok": False, "error": str(exc)}

    return {
        "specialists": specialists,
        "max_handoffs": settings.agent_max_handoffs,
        "max_tool_iterations": settings.agent_max_tool_iterations,
        "graph": {
            "nodes": sorted(agent_service.agent_graph.get_graph().nodes),
            "checkpointing": settings.checkpoint_backend,
        },
        "tools": tool_health,
        "mcp": await mcp_service.status(),
        "embeddings": await embedding_service.describe(),
    }
