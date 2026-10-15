"""Agenda de atendimento do professor (rotas autenticadas).

O aluno vê o resultado no portal (`student_portal`); aqui o professor cadastra as faixas
semanais e as exceções por data.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import AvailabilityExceptionModel, AvailabilitySlotModel, get_db
from ..core.security import get_current_user
from ..services import availability_service as svc

router = APIRouter(prefix="/education/availability", tags=["education-availability"])


class SlotIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: str = Field(max_length=5)
    end_time: str = Field(max_length=5)
    mode: str = "ambos"
    location: str = Field(default="", max_length=255)
    audience: str = "todos"
    note: str = Field(default="", max_length=255)
    active: bool = True


class SlotPatch(BaseModel):
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    start_time: Optional[str] = Field(default=None, max_length=5)
    end_time: Optional[str] = Field(default=None, max_length=5)
    mode: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=255)
    audience: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=255)
    active: Optional[bool] = None


class ExceptionIn(BaseModel):
    day: str = Field(max_length=10)
    kind: str = "blocked"
    start_time: str = Field(default="", max_length=5)
    end_time: str = Field(default="", max_length=5)
    mode: str = "ambos"
    location: str = Field(default="", max_length=255)
    audience: str = "todos"
    note: str = Field(default="", max_length=255)


def _slot_out(item: AvailabilitySlotModel) -> dict[str, Any]:
    return dict(
        id=item.id, weekday=item.weekday, weekday_name=svc.WEEKDAY_NAMES[item.weekday],
        start_time=item.start_time, end_time=item.end_time, mode=item.mode,
        location=item.location, audience=item.audience, note=item.note, active=bool(item.active))


def _exception_out(item: AvailabilityExceptionModel) -> dict[str, Any]:
    return dict(
        id=item.id, day=item.day, kind=item.kind, start_time=item.start_time,
        end_time=item.end_time, mode=item.mode, location=item.location,
        audience=item.audience, note=item.note)


def _fail(exc: svc.AvailabilityError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _owned(model, item_id: str, tutor_id: str, db: AsyncSession, label: str):
    item = await db.get(model, item_id)
    if item is None or item.tutor_id != tutor_id:
        raise HTTPException(404, f"{label} não encontrada")
    return item


@router.get("")
async def overview(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """As faixas semanais e as exceções de hoje em diante."""
    tutor = user["tutor_id"]
    return {
        "slots": [_slot_out(s) for s in await svc.list_slots(db, tutor)],
        "exceptions": [_exception_out(e) for e in
                       await svc.list_exceptions(db, tutor, from_day=svc.today().isoformat())],
    }


@router.get("/preview")
async def preview(
    days: int = 28,
    audience: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """As ocorrências datadas dos próximos dias; `audience` mostra como um aluno veria."""
    wanted = None
    if audience:
        if audience not in svc.AUDIENCES:
            raise HTTPException(400, "Público inválido.")
        wanted = {audience}
    items = await svc.occurrences(db, user["tutor_id"], days=days, wanted=wanted)
    return {"start": svc.today().isoformat(), "days": max(1, min(days, svc.MAX_DAYS)),
            "occurrences": items}


@router.post("/slots")
async def create_slot(
    body: SlotIn, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        data = svc.validate_slot(body.model_dump())
    except svc.AvailabilityError as exc:
        raise _fail(exc) from exc
    item = AvailabilitySlotModel(tutor_id=user["tutor_id"], active=body.active, **data)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _slot_out(item)


@router.patch("/slots/{slot_id}")
async def update_slot(
    slot_id: str, body: SlotPatch, user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(AvailabilitySlotModel, slot_id, user["tutor_id"], db, "Faixa")
    merged = {
        "weekday": item.weekday, "start_time": item.start_time, "end_time": item.end_time,
        "mode": item.mode, "location": item.location, "audience": item.audience,
        "note": item.note,
        **{k: v for k, v in body.model_dump().items() if v is not None and k != "active"},
    }
    try:
        data = svc.validate_slot(merged)
    except svc.AvailabilityError as exc:
        raise _fail(exc) from exc
    for key, value in data.items():
        setattr(item, key, value)
    if body.active is not None:
        item.active = body.active
    await db.commit()
    return _slot_out(item)


@router.delete("/slots/{slot_id}")
async def delete_slot(
    slot_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    item = await _owned(AvailabilitySlotModel, slot_id, user["tutor_id"], db, "Faixa")
    await db.delete(item)
    await db.commit()
    return {"ok": True}


@router.post("/exceptions")
async def create_exception(
    body: ExceptionIn, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        data = svc.validate_exception(body.model_dump())
    except svc.AvailabilityError as exc:
        raise _fail(exc) from exc
    item = AvailabilityExceptionModel(tutor_id=user["tutor_id"], **data)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _exception_out(item)


@router.delete("/exceptions/{exception_id}")
async def delete_exception(
    exception_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    item = await _owned(AvailabilityExceptionModel, exception_id, user["tutor_id"], db, "Exceção")
    await db.delete(item)
    await db.commit()
    return {"ok": True}
