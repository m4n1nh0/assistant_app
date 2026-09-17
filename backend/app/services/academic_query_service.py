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


#: Pedido sobre o que aconteceu DENTRO de uma aula. "aula do dia 10/09" casa as
#: palavras de agenda, mas "resumo", "sobre" ou "o que foi visto" dizem que a
#: pessoa quer o conteudo - e quem responde isso e o contexto das aulas gravadas,
#: nao a projecao de horarios.
_LESSON_CONTENT = re.compile(
    r"\b(resum\w*|conteudo\w*|materia\w*|assunto\w*|topico\w*|transcri\w*"
    r"|explica\w*|revis\w*|detalh\w*"
    r"|o que (?:foi|a gente|nos|eu|voce|vimos|vi|falamos|falei|estudamos|aprendemos|dei|passei|passou|teve))\b"
)
#: "sobre" sozinho e ambiguo: "buscar sobre a aula do dia 10/09" quer conteudo,
#: "horarios das aulas sobre banco de dados" quer agenda. So vale como pedido de
#: conteudo quando nenhuma palavra forte de agenda aparece junto.
_ABOUT = re.compile(r"\bsobre\b")
_STRONG_SCHEDULE = re.compile(r"\b(quando|horario\w*|agenda\w*|calendario\w*|proxim\w*)\b")


def is_academic_schedule_query(
    message: str,
    *,
    timezone_name: str = "America/Sao_Paulo",
    now: datetime | None = None,
) -> bool:
    """Diz se a pergunta e sobre a agenda de aulas, e nao sobre uma aula dada.

    A resposta desta rota projeta as proximas semanas a partir dos horarios
    semanais. Por isso ela nao serve a duas perguntas que tambem falam de "aula"
    e "dia": o conteudo de uma aula ("resumo da aula do dia 10/09") e uma data
    que ja passou ("tive aula dia 10/09?") - nas duas, a lista de aulas futuras
    ignoraria a data pedida.
    """
    text = _plain(message)
    if not (re.search(r"\b(aula|aulas|turma|turmas|disciplina|disciplinas)\b", text)
            and re.search(r"\b(quando|data|datas|dia|dias|horario|horarios|agenda|calendario|proxim|listar|trazer|tracar)\w*\b", text)):
        return False
    if _LESSON_CONTENT.search(text):
        return False
    if _ABOUT.search(text) and not _STRONG_SCHEDULE.search(text):
        return False

    from .lesson_context_service import parse_day

    day, _ = parse_day(message, timezone_name=timezone_name, now=now)
    if day is not None:
        today = (now.astimezone(ZoneInfo(timezone_name)) if now else datetime.now(ZoneInfo(timezone_name))).date()
        if day < today:
            return False
    return True


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
