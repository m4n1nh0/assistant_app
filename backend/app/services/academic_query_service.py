"""Consulta de leitura dos horarios de aula registrados no banco interno."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..core.database import (
    AsyncSessionLocal, ClassGroupModel, ClassScheduleModel, DisciplineModel,
)


def _plain(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower())
                   if not unicodedata.combining(c))


def is_academic_schedule_query(message: str) -> bool:
    text = _plain(message)
    return bool(re.search(r"\b(aula|aulas|turma|turmas|disciplina|disciplinas)\b", text)
                and re.search(r"\b(quando|data|datas|dia|dias|horario|horarios|agenda|calendario|proxim|listar|listar|trazer|tracar)\w*\b", text))


async def academic_schedule_response(tutor_id: str, timezone_name: str) -> str:
    """Lista as proximas quatro semanas; o tutor vem da sessao autenticada."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ClassGroupModel, ClassScheduleModel, DisciplineModel)
            .join(ClassScheduleModel, ClassScheduleModel.class_group_id == ClassGroupModel.id)
            .outerjoin(DisciplineModel, DisciplineModel.id == ClassGroupModel.discipline_id)
            .where(ClassGroupModel.tutor_id == tutor_id, ClassGroupModel.active.is_(True))
            .order_by(ClassGroupModel.code, ClassScheduleModel.weekday)
        )).all()
    if not rows:
        return "Não encontrei horários de aula cadastrados para suas turmas no banco interno."

    today = datetime.now(ZoneInfo(timezone_name)).date()
    entries: list[tuple] = []
    for group, schedule, discipline in rows:
        if not 0 <= schedule.weekday <= 6:
            continue
        # O horario semanal nao guarda excecoes ou limite do semestre.
        first = today + timedelta(days=(schedule.weekday - today.weekday()) % 7)
        for week in range(4):
            day = first + timedelta(weeks=week)
            if day >= today + timedelta(days=28):
                continue
            name = discipline.name if discipline and discipline.tutor_id == tutor_id else group.discipline
            code = discipline.code if discipline and discipline.tutor_id == tutor_id else ""
            label = " ".join(part for part in (code, name) if part).strip() or "Disciplina sem nome"
            group_label = " ".join(part for part in (group.code, group.name) if part).strip()
            hours = (f"{schedule.start_time}–{schedule.end_time}" if schedule.start_time and schedule.end_time
                     else schedule.start_time or "horário não informado")
            entries.append((day, schedule.start_time, label, group_label, hours))
    entries.sort()
    if not entries:
        return "Encontrei turmas, mas nenhum horário semanal válido cadastrado."
    lines = [f"- {day:%d/%m/%Y}: {label} — turma {group} — {hours}"
             for day, _, label, group, hours in entries[:80]]
    return ("Próximas aulas conforme os horários semanais cadastrados:\n"
            + "\n".join(lines)
            + "\nEssas datas são projeções da rotina semanal; feriados, cancelamentos e o fim do semestre não estão registrados nesse horário.")
