"""Sorteio da ordem de apresentacao dos grupos de projeto.

A regra do sorteio (e o que o faz verificavel) esta em `group_draw_service`; aqui
ficam a gravacao, o isolamento por professor e as transicoes de estado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ClassGroupModel,
    DisciplineModel,
    GroupDrawEntryModel,
    GroupDrawModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    get_db,
)
from ..core.security import get_current_user
from ..services import group_draw_service as rule
from ..services.project_group_service import class_labels

router = APIRouter(prefix="/education/group-draws", tags=["education-group-draws"])

ENTRY_STATUSES = ("pendente", "apresentando", "apresentou", "ausente")


class GroupDrawCreate(BaseModel):
    discipline_id: str
    semester: str = ""
    title: str = Field(default="", max_length=255)
    #: Turma (dia de aula) que sorteia. Vazio: os grupos de todas as turmas.
    class_id: Optional[str] = None
    mode: Literal["fila", "avulso"] = "fila"
    #: Quantos grupos apresentam por dia. Vazio: todos no mesmo dia.
    per_day: Optional[int] = Field(default=None, ge=1, le=50)
    #: Subconjunto dos grupos da disciplina. Vazio: todos.
    group_ids: list[str] = Field(default_factory=list)


class EntryStatusUpdate(BaseModel):
    status: Literal["pendente", "apresentando", "apresentou", "ausente"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _discipline_label(item: DisciplineModel) -> str:
    partes = [(item.code or "").strip(), (item.name or "").strip()]
    return " - ".join(parte for parte in partes if parte) or "disciplina"


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _entry_out(entry: GroupDrawEntryModel) -> dict:
    return dict(
        id=entry.id,
        group_id=entry.group_id,
        group_name=entry.group_name,
        position=entry.position,
        day=entry.day,
        status=entry.status,
        representative_member_id=entry.representative_member_id,
        representative_name=entry.representative_name,
        representative_round=entry.representative_round,
        drawn_at=_iso(entry.drawn_at),
        presented_at=_iso(entry.presented_at),
    )


async def _owned_draw(draw_id: str, tutor_id: str, db: AsyncSession) -> GroupDrawModel:
    draw = await db.get(GroupDrawModel, draw_id)
    if draw is None or draw.tutor_id != tutor_id:
        raise HTTPException(404, "Sorteio nao encontrado")
    return draw


async def _entries_of(draw_id: str, db: AsyncSession) -> list[GroupDrawEntryModel]:
    rows = (
        await db.execute(
            select(GroupDrawEntryModel).where(GroupDrawEntryModel.draw_id == draw_id)
        )
    ).scalars().all()
    # Quem ja saiu vem pela ordem da vez; quem ainda nao saiu, por nome.
    return sorted(
        rows,
        key=lambda item: (
            item.position is None,
            item.position or 0,
            (item.group_name or "").lower(),
        ),
    )


async def _draw_out(draw: GroupDrawModel, db: AsyncSession) -> dict:
    entries = await _entries_of(draw.id, db)
    discipline = await db.get(DisciplineModel, draw.discipline_id)
    turmas = await class_labels(db, draw.tutor_id, [draw.class_id])
    sorteados = [item.group_id for item in entries if item.position is not None]
    return dict(
        id=draw.id,
        discipline_id=draw.discipline_id,
        discipline=_discipline_label(discipline) if discipline else "",
        class_id=draw.class_id,
        class_label=turmas.get(draw.class_id, {}).get("display", ""),
        semester=draw.semester,
        title=draw.title,
        mode=draw.mode,
        seed=draw.seed,
        algorithm=draw.algorithm,
        per_day=draw.per_day,
        step=draw.step,
        total=len(entries),
        remaining=len(entries) - len(sorteados),
        verified=rule.verify_order(
            draw.seed, [item.group_id for item in entries], sorteados
        ),
        created_at=_iso(draw.created_at),
        entries=[_entry_out(item) for item in entries],
    )


@router.post("")
async def create_draw(
    body: GroupDrawCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cria o sorteio. Na fila completa a ordem ja sai pronta; no avulso, vazia."""
    tutor_id = user["tutor_id"]
    discipline = await db.get(DisciplineModel, body.discipline_id)
    if discipline is None or discipline.tutor_id != tutor_id:
        raise HTTPException(404, "Disciplina nao encontrada")

    class_id = (body.class_id or "").strip() or None
    if class_id:
        turma = await db.get(ClassGroupModel, class_id)
        if turma is None or turma.tutor_id != tutor_id:
            raise HTTPException(404, "Turma nao encontrada")
        if turma.discipline_id != body.discipline_id:
            raise HTTPException(422, "Essa turma nao e desta disciplina")

    query = select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == tutor_id,
        ProjectGroupModel.discipline_id == body.discipline_id,
    )
    if class_id:
        query = query.where(ProjectGroupModel.class_id == class_id)
    semester = body.semester.strip()
    if semester:
        query = query.where(ProjectGroupModel.semester == semester)
    groups = {
        item.id: item for item in (await db.execute(query)).scalars().all()
    }

    if body.group_ids:
        desconhecidos = [gid for gid in body.group_ids if gid not in groups]
        if desconhecidos:
            raise HTTPException(
                422, "Ha grupo escolhido que nao pertence a essa disciplina e semestre"
            )
        groups = {gid: groups[gid] for gid in dict.fromkeys(body.group_ids)}
    if not groups:
        raise HTTPException(
            422,
            "Essa turma nao tem grupos de projeto para sortear"
            if class_id else "Essa disciplina nao tem grupos de projeto para sortear",
        )

    turma_label = (await class_labels(db, tutor_id, [class_id])).get(class_id, {}).get("display", "")
    draw = GroupDrawModel(
        tutor_id=tutor_id,
        discipline_id=body.discipline_id,
        class_id=class_id,
        semester=semester,
        title=body.title.strip()
        or " - ".join(part for part in (
            "Ordem de apresentacao", _discipline_label(discipline), turma_label) if part),
        mode=body.mode,
        seed=rule.new_seed(),
        algorithm=rule.ALGORITHM,
        per_day=body.per_day,
        step=0,
    )
    db.add(draw)
    await db.flush()

    entries = {
        gid: GroupDrawEntryModel(draw_id=draw.id, group_id=gid, group_name=item.name)
        for gid, item in groups.items()
    }
    if body.mode == rule.MODE_QUEUE:
        agora = _now()
        for posicao, gid in enumerate(rule.draw_order(draw.seed, list(groups)), start=1):
            entry = entries[gid]
            entry.position = posicao
            entry.day = rule.day_of(posicao, draw.per_day)
            entry.drawn_at = agora
        draw.step = len(entries)
    db.add_all(entries.values())
    await db.commit()
    await db.refresh(draw)
    return await _draw_out(draw, db)


@router.get("")
async def list_draws(
    discipline_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sorteios do professor, do mais recente ao mais antigo, sem as linhas."""
    query = select(GroupDrawModel).where(GroupDrawModel.tutor_id == user["tutor_id"])
    if discipline_id:
        query = query.where(GroupDrawModel.discipline_id == discipline_id)
    draws = (
        await db.execute(query.order_by(GroupDrawModel.created_at.desc()))
    ).scalars().all()
    resultado = []
    for draw in draws:
        detalhe = await _draw_out(draw, db)
        detalhe.pop("entries")
        resultado.append(detalhe)
    return resultado


@router.get("/{draw_id}")
async def get_draw(
    draw_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _draw_out(await _owned_draw(draw_id, user["tutor_id"], db), db)


@router.post("/{draw_id}/next")
async def draw_next(
    draw_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sorteia o proximo grupo do modo avulso."""
    draw = await _owned_draw(draw_id, user["tutor_id"], db)
    if draw.mode != rule.MODE_ONE_BY_ONE:
        raise HTTPException(409, "A ordem desse sorteio ja saiu inteira")

    restantes = [
        item for item in await _entries_of(draw.id, db) if item.position is None
    ]
    if not restantes:
        raise HTTPException(409, "Todos os grupos ja foram sorteados")

    # Dois cliques seguidos nao podem sortear o mesmo passo duas vezes: so quem
    # avanca o contador a partir do valor que leu grava o resultado.
    passo = draw.step
    avancou = await db.execute(
        update(GroupDrawModel)
        .where(GroupDrawModel.id == draw.id, GroupDrawModel.step == passo)
        .values(step=passo + 1)
    )
    if avancou.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Outro sorteio acabou de acontecer; confira a tela")

    escolhido = rule.pick_step(draw.seed, passo, [item.group_id for item in restantes])
    entry = next(item for item in restantes if item.group_id == escolhido)
    entry.position = passo + 1
    entry.day = rule.day_of(entry.position, draw.per_day)
    entry.drawn_at = _now()
    await db.commit()
    await db.refresh(draw)
    return await _draw_out(draw, db)


async def _owned_entry(
    draw: GroupDrawModel, entry_id: str, db: AsyncSession
) -> GroupDrawEntryModel:
    entry = await db.get(GroupDrawEntryModel, entry_id)
    if entry is None or entry.draw_id != draw.id:
        raise HTTPException(404, "Grupo nao encontrado nesse sorteio")
    return entry


@router.patch("/{draw_id}/entries/{entry_id}")
async def update_entry_status(
    draw_id: str,
    entry_id: str,
    body: EntryStatusUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Marca a apresentacao: na vez, feita ou ausente."""
    draw = await _owned_draw(draw_id, user["tutor_id"], db)
    entry = await _owned_entry(draw, entry_id, db)
    if entry.position is None:
        raise HTTPException(409, "Esse grupo ainda nao foi sorteado")

    entry.status = body.status
    entry.presented_at = _now() if body.status == "apresentou" else None
    await db.commit()
    return await _draw_out(draw, db)


@router.post("/{draw_id}/entries/{entry_id}/representative")
async def draw_representative(
    draw_id: str,
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sorteia o integrante que representa o grupo; chamar de novo sorteia outro.

    A rodada sobe a cada chamada e fica gravada, entao um novo sorteio (o escolhido
    faltou) tambem pode ser conferido depois.
    """
    draw = await _owned_draw(draw_id, user["tutor_id"], db)
    entry = await _owned_entry(draw, entry_id, db)

    members = (
        await db.execute(
            select(ProjectGroupMemberModel).where(
                ProjectGroupMemberModel.group_id == entry.group_id
            )
        )
    ).scalars().all()
    if not members:
        raise HTTPException(422, "O grupo nao tem integrantes cadastrados")

    rodada = 0 if entry.representative_member_id is None else entry.representative_round + 1
    if len(members) == 1:
        rodada = 0
    escolhido = rule.pick_representative(
        draw.seed, entry.group_id, [item.id for item in members], round_=rodada
    )
    membro = next(item for item in members if item.id == escolhido)
    entry.representative_member_id = membro.id
    entry.representative_name = membro.name
    entry.representative_round = rodada
    await db.commit()
    return await _draw_out(draw, db)


@router.delete("/{draw_id}")
async def delete_draw(
    draw_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    draw = await _owned_draw(draw_id, user["tutor_id"], db)
    for entry in await _entries_of(draw.id, db):
        await db.delete(entry)
    await db.delete(draw)
    await db.commit()
    return {"deleted": draw_id}
