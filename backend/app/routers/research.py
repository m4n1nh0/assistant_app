"""Pesquisas científicas: projetos, participantes e etapas do plano (rotas do professor)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ResearchParticipantModel,
    ResearchProjectModel,
    ResearchStageModel,
    get_db,
)
from ..core.security import get_current_user
from ..services import research_service as svc

router = APIRouter(prefix="/education/research", tags=["education-research"])


class PlanBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    weeks: int = Field(default=24, ge=2, le=260)
    start_date: Optional[datetime] = None


class StageIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    due_at: Optional[datetime] = None


class ParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    role: str = "orientando"
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=40)
    enrollment: str = Field(default="", max_length=80)
    institution: str = Field(default="", max_length=180)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    area: str = Field(default="", max_length=120)
    semester: str = Field(default="", max_length=16)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    stages: list[StageIn] = Field(default_factory=list, max_length=svc.MAX_STAGES)
    participants: list[ParticipantIn] = Field(default_factory=list, max_length=50)


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    area: Optional[str] = Field(default=None, max_length=120)
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    clear_dates: bool = False


class StageUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = None
    due_at: Optional[datetime] = None
    clear_due: bool = False


class ParticipantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=180)
    role: Optional[str] = None
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=40)
    institution: Optional[str] = Field(default=None, max_length=180)


def _project_out(item: ResearchProjectModel, summary: dict) -> dict[str, Any]:
    return dict(
        id=item.id, title=item.title, description=item.description, area=item.area,
        semester=item.semester, status=item.status, start_date=item.start_date,
        end_date=item.end_date, created_at=item.created_at, **{
            f"{k}": v for k, v in summary.items()})


def _stage_out(item: ResearchStageModel) -> dict[str, Any]:
    return dict(
        id=item.id, title=item.title, description=item.description, due_at=item.due_at,
        status=item.status, state=svc.stage_state(item), position=item.position,
        done_at=item.done_at)


def _participant_out(item: ResearchParticipantModel) -> dict[str, Any]:
    return dict(
        id=item.id, name=item.name, email=item.email, phone=item.phone,
        enrollment=item.enrollment, institution=item.institution, role=item.role,
        known_student=bool(item.known_student))


async def _owned(project_id: str, tutor_id: str, db: AsyncSession) -> ResearchProjectModel:
    item = await db.get(ResearchProjectModel, project_id)
    if item is None or item.tutor_id != tutor_id:
        raise HTTPException(404, "Pesquisa não encontrada")
    return item


async def _owned_child(model, child_id: str, tutor_id: str, db: AsyncSession, label: str):
    item = await db.get(model, child_id)
    if item is None or item.tutor_id != tutor_id:
        raise HTTPException(404, f"{label} não encontrada")
    return item


@router.post("/generate-plan")
async def generate_plan(body: PlanBody, user: dict = Depends(get_current_user)):
    """A IA propõe as etapas, já com datas; nada é gravado até o professor criar."""
    stages, from_ai = await svc.generate_plan(
        body.title, body.description, weeks=body.weeks, start=body.start_date)
    return {"stages": [{"title": s["title"], "description": s["description"],
                        "due_at": s["due_at"]} for s in stages], "from_ai": from_ai}


@router.post("")
async def create_project(
    body: ProjectCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = ResearchProjectModel(
        tutor_id=user["tutor_id"], title=" ".join(body.title.split()),
        description=body.description.strip(), area=" ".join(body.area.split()),
        semester=body.semester.strip(), status="planning",
        start_date=svc.naive(body.start_date), end_date=svc.naive(body.end_date))
    db.add(project)
    await db.flush()
    for position, stage in enumerate(body.stages):
        db.add(ResearchStageModel(
            project_id=project.id, tutor_id=project.tutor_id,
            title=" ".join(stage.title.split()), description=stage.description.strip(),
            due_at=svc.naive(stage.due_at), position=position))
    await db.commit()
    try:
        for person in body.participants:
            await svc.add_participant(db, project, person.model_dump())
    except svc.ResearchError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    await db.refresh(project)
    return _project_out(project, await svc.summary(db, project))


@router.get("")
async def list_projects(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ResearchProjectModel).where(
        ResearchProjectModel.tutor_id == user["tutor_id"]
    ).order_by(ResearchProjectModel.created_at.desc()))).scalars().all()
    return [_project_out(item, await svc.summary(db, item)) for item in rows]


@router.get("/{project_id}")
async def project_detail(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _owned(project_id, user["tutor_id"], db)
    return {
        "project": _project_out(project, await svc.summary(db, project)),
        "stages": [_stage_out(s) for s in await svc.stages_of(db, project.id)],
        "participants": [_participant_out(p) for p in await svc.participants_of(db, project.id)],
    }


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _owned(project_id, user["tutor_id"], db)
    if body.title is not None:
        project.title = " ".join(body.title.split())
    if body.description is not None:
        project.description = body.description.strip()
    if body.area is not None:
        project.area = " ".join(body.area.split())
    if body.status is not None:
        if body.status not in svc.PROJECT_STATUSES:
            raise HTTPException(400, "Situação inválida.")
        project.status = body.status
    if body.clear_dates:
        project.start_date = project.end_date = None
    else:
        if body.start_date is not None:
            project.start_date = svc.naive(body.start_date)
        if body.end_date is not None:
            project.end_date = svc.naive(body.end_date)
    await db.commit()
    return _project_out(project, await svc.summary(db, project))


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apaga a pesquisa com as etapas e os participantes dela."""
    project = await _owned(project_id, user["tutor_id"], db)
    for model in (ResearchStageModel, ResearchParticipantModel):
        await db.execute(delete(model).where(model.project_id == project.id))
    await db.delete(project)
    await db.commit()
    return {"ok": True}


# --- participantes -----------------------------------------------------------------------


@router.post("/{project_id}/participants")
async def add_participant(
    project_id: str,
    body: ParticipantIn,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _owned(project_id, user["tutor_id"], db)
    try:
        person = await svc.add_participant(db, project, body.model_dump())
    except svc.ResearchError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return _participant_out(person)


@router.patch("/participants/{participant_id}")
async def update_participant(
    participant_id: str,
    body: ParticipantUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned_child(
        ResearchParticipantModel, participant_id, user["tutor_id"], db, "Participante")
    if body.name is not None:
        item.name = " ".join(body.name.split())
    if body.role is not None:
        if body.role not in svc.ROLES:
            raise HTTPException(400, "Papel inválido.")
        item.role = body.role
    for field in ("email", "phone", "institution"):
        value = getattr(body, field)
        if value is not None:
            setattr(item, field, value.strip())
    await db.commit()
    return _participant_out(item)


@router.delete("/participants/{participant_id}")
async def remove_participant(
    participant_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tira da pesquisa sem apagar o registro (o histórico fica)."""
    item = await _owned_child(
        ResearchParticipantModel, participant_id, user["tutor_id"], db, "Participante")
    item.active = False
    await db.commit()
    return {"ok": True}


# --- etapas ------------------------------------------------------------------------------


@router.post("/{project_id}/stages")
async def add_stage(
    project_id: str,
    body: StageIn,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _owned(project_id, user["tutor_id"], db)
    position = len(await svc.stages_of(db, project.id))
    stage = ResearchStageModel(
        project_id=project.id, tutor_id=project.tutor_id, title=" ".join(body.title.split()),
        description=body.description.strip(), due_at=svc.naive(body.due_at), position=position)
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return _stage_out(stage)


@router.patch("/stages/{stage_id}")
async def update_stage(
    stage_id: str,
    body: StageUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stage = await _owned_child(ResearchStageModel, stage_id, user["tutor_id"], db, "Etapa")
    if body.title is not None:
        stage.title = " ".join(body.title.split())
    if body.description is not None:
        stage.description = body.description.strip()
    if body.clear_due:
        stage.due_at = None
    elif body.due_at is not None:
        stage.due_at = svc.naive(body.due_at)
    if body.status is not None:
        try:
            svc.apply_stage_status(stage, body.status)
        except svc.ResearchError as exc:
            raise HTTPException(exc.status, exc.message) from exc
    await db.commit()
    return _stage_out(stage)


@router.delete("/stages/{stage_id}")
async def delete_stage(
    stage_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stage = await _owned_child(ResearchStageModel, stage_id, user["tutor_id"], db, "Etapa")
    await db.delete(stage)
    await db.commit()
    return {"ok": True}
