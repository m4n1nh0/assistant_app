from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import ShortcutLaunchLogModel, ShortcutModel, get_db
from ..models.schemas import (
    ShortcutCreate,
    ShortcutLaunchRequest,
    ShortcutLaunchResponse,
    ShortcutResponse,
    ShortcutType,
    ShortcutUpdate,
)
from ..core.security import get_current_user
from ..services.launcher_service import record_launch, suggest_launch_command

router = APIRouter(prefix="/launcher", tags=["Launcher"], dependencies=[Depends(get_current_user)])


def _to_response(sc: ShortcutModel) -> ShortcutResponse:
    return ShortcutResponse(
        id=sc.id,
        tutor_id=sc.tutor_id,
        name=sc.name,
        type=ShortcutType(sc.type),
        target=sc.target,
        aliases=sc.aliases or [],
        description=sc.description,
        use_count=sc.use_count or 0,
        last_used_at=sc.last_used_at,
        created_at=sc.created_at,
    )


def _launch_response(item: ShortcutLaunchLogModel) -> ShortcutLaunchResponse:
    return ShortcutLaunchResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        shortcut_id=item.shortcut_id,
        shortcut_name=item.shortcut_name,
        target_type=item.target_type,
        target=item.target,
        status=item.status,
        source=item.source,
        platform=item.platform,
        request=item.request or {},
        result=item.result or {},
        error=item.error,
        launched_at=item.launched_at,
    )


@router.get("/suggest-command")
async def suggest_command_endpoint(name: str):
    """Find the Windows executable for an app using 'where' + LLM fallback."""
    target = await suggest_launch_command(name.strip())
    return {"target": target or ""}


@router.post("/shortcuts", response_model=ShortcutResponse, status_code=201)
async def create_shortcut(body: ShortcutCreate, db: AsyncSession = Depends(get_db)):
    name = body.name.strip()
    target = body.target.strip()
    aliases = [item.strip() for item in body.aliases if item.strip()]
    if not name:
        raise HTTPException(400, "Nome do atalho nao pode ficar vazio")
    if not target:
        raise HTTPException(400, "Destino do atalho nao pode ficar vazio")
    sc = ShortcutModel(
        tutor_id=body.tutor_id,
        name=name,
        type=body.type.value,
        target=target,
        aliases=aliases,
        description=body.description.strip() if body.description else None,
    )
    db.add(sc)
    await db.commit()
    await db.refresh(sc)
    return _to_response(sc)


@router.get("/launches", response_model=list[ShortcutLaunchResponse])
async def list_launches(
    tutor_id: str,
    shortcut_id: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(ShortcutLaunchLogModel).where(
        ShortcutLaunchLogModel.tutor_id == tutor_id
    )
    if shortcut_id:
        query = query.where(ShortcutLaunchLogModel.shortcut_id == shortcut_id)
    if status:
        query = query.where(ShortcutLaunchLogModel.status == status)
    if date_from:
        query = query.where(ShortcutLaunchLogModel.launched_at >= date_from)
    if date_to:
        query = query.where(ShortcutLaunchLogModel.launched_at <= date_to)

    result = await db.execute(
        query.order_by(ShortcutLaunchLogModel.launched_at.desc()).limit(limit)
    )
    return [_launch_response(item) for item in result.scalars().all()]


@router.get("/shortcuts", response_model=list[ShortcutResponse])
async def list_shortcuts(tutor_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ShortcutModel)
        .where(ShortcutModel.tutor_id == tutor_id)
        .order_by(ShortcutModel.use_count.desc(), ShortcutModel.name)
    )
    return [_to_response(sc) for sc in result.scalars().all()]


@router.patch("/shortcuts/{shortcut_id}", response_model=ShortcutResponse)
async def update_shortcut(
    shortcut_id: str,
    body: ShortcutUpdate,
    db: AsyncSession = Depends(get_db),
):
    sc = await db.get(ShortcutModel, shortcut_id)
    if sc is None:
        raise HTTPException(404, "Atalho não encontrado")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "Nome do atalho nao pode ficar vazio")
        sc.name = name
    if body.type is not None:
        sc.type = body.type.value
    if body.target is not None:
        target = body.target.strip()
        if not target:
            raise HTTPException(400, "Destino do atalho nao pode ficar vazio")
        sc.target = target
    if body.aliases is not None:
        sc.aliases = [item.strip() for item in body.aliases if item.strip()]
    if body.description is not None:
        description = body.description.strip()
        sc.description = description or None
    await db.commit()
    await db.refresh(sc)
    return _to_response(sc)


@router.delete("/shortcuts/{shortcut_id}", status_code=204)
async def delete_shortcut(shortcut_id: str, db: AsyncSession = Depends(get_db)):
    sc = await db.get(ShortcutModel, shortcut_id)
    if sc is None:
        raise HTTPException(404, "Atalho não encontrado")
    await db.delete(sc)
    await db.commit()


@router.post("/shortcuts/{shortcut_id}/launched", response_model=ShortcutResponse)
async def confirm_launched(
    shortcut_id: str,
    body: ShortcutLaunchRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Interface calls this after an app/URL launch attempt."""
    body = body or ShortcutLaunchRequest()
    await record_launch(
        shortcut_id,
        db,
        status=body.status,
        source=body.source,
        platform=body.platform,
        request=body.request,
        result=body.result,
        error=body.error,
    )
    sc = await db.get(ShortcutModel, shortcut_id)
    if sc is None:
        raise HTTPException(404, "Atalho não encontrado")
    return _to_response(sc)
