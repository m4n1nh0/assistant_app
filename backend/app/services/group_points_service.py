"""Pontos lançados ao grupo de projeto, com histórico.

Cada lançamento é uma linha: pontos (positivo soma, negativo tira), motivo e data. O total
do grupo é a soma dos lançamentos. Na hora de lançar, o professor escolhe se o ponto vale
só para o grupo ou também para cada integrante ligado a um aluno; nesse caso o lançamento
vira ponto extra de cada um (o mesmo `LessonPointModel` dos pontos extras de aula), e
aparece na aba Pontuações. Apagar ou corrigir o lançamento refaz o que foi creditado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    DisciplineModel,
    LessonPointModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    ProjectGroupPointModel,
    StudentModel,
)

#: Os pontos creditados aos integrantes guardam, no lugar da aula, esta marca + o id do
#: lançamento: é por ela que se apagam ou refazem junto com o lançamento.
CREDIT_PREFIX = "group-points:"
CREDIT_SOURCE = "group"

MAX_POINTS = 100.0


def credit_lesson_id(entry_id: str) -> str:
    return f"{CREDIT_PREFIX}{entry_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _discipline_label(item: Optional[DisciplineModel]) -> str:
    if item is None:
        return ""
    return " - ".join(part for part in ((item.code or "").strip(),
                                        (item.name or "").strip()) if part)


async def _remove_credits(db: AsyncSession, entry_ids: Sequence[str]) -> None:
    ids = [credit_lesson_id(item) for item in entry_ids]
    for start in range(0, len(ids), 500):
        await db.execute(sql_delete(LessonPointModel).where(
            LessonPointModel.lesson_id.in_(ids[start:start + 500])))


async def credit_members(db: AsyncSession, group: ProjectGroupModel,
                         entry: ProjectGroupPointModel) -> dict:
    """Credita o lançamento a cada integrante ligado a um aluno; devolve o resumo."""
    members = (await db.execute(select(ProjectGroupMemberModel).where(
        ProjectGroupMemberModel.group_id == group.id
    ).order_by(ProjectGroupMemberModel.position))).scalars().all()
    linked = [member for member in members if member.student_id]
    students = {
        student.id: student for student in (await db.execute(
            select(StudentModel).where(
                StudentModel.tutor_id == group.tutor_id,
                StudentModel.id.in_([member.student_id for member in linked] or [""]),
            ))).scalars().all()
    }
    discipline = _discipline_label(await db.get(DisciplineModel, group.discipline_id))
    reason = f"{group.name}: {entry.reason}" if entry.reason else group.name
    credited = set()
    for member in linked:
        student = students.get(member.student_id)
        if student is None or student.id in credited:
            continue
        credited.add(student.id)
        db.add(LessonPointModel(
            tutor_id=group.tutor_id,
            lesson_id=credit_lesson_id(entry.id),
            student_id=student.id,
            student_name=student.name,
            points=entry.points,
            reason=reason[:2000],
            discipline=discipline,
            lesson_date=entry.entry_date,
            source=CREDIT_SOURCE,
            confidence=1.0,
        ))
    entry.credited_count = len(credited)
    return dict(credited=len(credited), without_link=len(members) - len(linked),
                members=len(members))


async def refresh_credits(db: AsyncSession, group: ProjectGroupModel,
                          entry: ProjectGroupPointModel) -> dict:
    """Refaz o que o lançamento creditou aos integrantes, conforme o estado dele agora."""
    await _remove_credits(db, [entry.id])
    if not entry.credit_members:
        entry.credited_count = 0
        return dict(credited=0, without_link=0, members=0)
    return await credit_members(db, group, entry)


def entry_out(entry: ProjectGroupPointModel, **extra) -> dict:
    return dict(
        id=entry.id, group_id=entry.group_id, points=entry.points,
        reason=entry.reason or "", entry_date=entry.entry_date,
        credit_members=bool(entry.credit_members),
        credited_count=int(entry.credited_count or 0),
        created_at=entry.created_at, **extra,
    )


async def totals_for_groups(db: AsyncSession, group_ids: Sequence[str]) -> dict[str, dict]:
    """Total e quantidade de lançamentos de cada grupo, numa consulta só."""
    if not group_ids:
        return {}
    rows = (await db.execute(
        select(ProjectGroupPointModel.group_id,
               func.coalesce(func.sum(ProjectGroupPointModel.points), 0.0),
               func.count())
        .where(ProjectGroupPointModel.group_id.in_(list(group_ids)))
        .group_by(ProjectGroupPointModel.group_id)
    )).all()
    return {group_id: dict(total=round(float(total), 3), count=int(count))
            for group_id, total, count in rows}


async def purge_for_groups(db: AsyncSession, group_ids: Sequence[str]) -> None:
    """Apaga os lançamentos de grupos que estão sendo apagados, e o que creditaram."""
    if not group_ids:
        return
    ids = list(group_ids)
    entry_ids: list[str] = []
    for start in range(0, len(ids), 500):
        entry_ids.extend((await db.execute(select(ProjectGroupPointModel.id).where(
            ProjectGroupPointModel.group_id.in_(ids[start:start + 500])))).scalars().all())
    await _remove_credits(db, entry_ids)
    for start in range(0, len(ids), 500):
        await db.execute(sql_delete(ProjectGroupPointModel).where(
            ProjectGroupPointModel.group_id.in_(ids[start:start + 500])))
