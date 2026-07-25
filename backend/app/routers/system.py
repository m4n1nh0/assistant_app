from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import get_db
from ..core.security import get_current_user
from ..services import qdrant_service

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
