from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import get_db
from ..core.security import get_current_user
from ..services import agent_service, embedding_service, mcp_service, qdrant_service

router = APIRouter(prefix="/system", tags=["System"], dependencies=[Depends(get_current_user)])
settings = get_settings()


@router.get("/storage/status")
async def storage_status(db: AsyncSession = Depends(get_db)):
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
    """Quem pode atender, com que ferramentas e com quais embeddings."""
    return {
        "specialists": [
            {
                "id": item.id,
                "label": item.label,
                "description": item.description,
                "routing_task": item.routing_task,
                "tools": list(item.tool_names),
                "uses_mcp": item.use_mcp,
            }
            for item in agent_service.SPECIALISTS.values()
        ],
        "max_handoffs": settings.agent_max_handoffs,
        "max_tool_iterations": settings.agent_max_tool_iterations,
        "mcp": await mcp_service.status(),
        "embeddings": await embedding_service.describe(),
    }
