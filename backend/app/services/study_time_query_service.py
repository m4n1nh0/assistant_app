"""Perguntas sobre tempo de estudo importado, com escopo do professor."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from sqlalchemy import select

from ..core.database import AsyncSessionLocal, StudentModel, StudyTimeModel
from .study_time_service import belongs_to_scope, owned_discipline_scope


def _plain(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value.lower())
                   if not unicodedata.combining(char))


def is_study_time_query(message: str) -> bool:
    text = _plain(message)
    return bool(re.search(r"\b(tempo|minutos?|horas?)\s+(?:de\s+)?estudo\b", text)
                or re.search(r"\bestudo\b.*\b(minutos?|horas?|ranking|total|media)\b", text)
                or (re.search(r"\bestud(?:ou|aram)\b", text)
                    and re.search(r"\b(alunos?|turmas?|disciplinas?|quanto|ranking)\b", text)))


async def study_time_chat_response(tutor_id: str, message: str) -> str:
    async with AsyncSessionLocal() as db:
        scope = await owned_discipline_scope(db, tutor_id)
        records = (await db.execute(
            select(StudyTimeModel, StudentModel.name)
            .outerjoin(StudentModel, (StudentModel.id == StudyTimeModel.student_id)
                       & (StudentModel.tutor_id == tutor_id))
            .where(StudyTimeModel.tutor_id == tutor_id)
        )).all()
    records = [(item, name) for item, name in records
               if belongs_to_scope(item.discipline_code, scope)]
    text = _plain(message)
    code = re.search(r"\b[Aa][Rr][Aa]\d{4}\b", message)
    if code:
        records = [(item, name) for item, name in records
                   if item.discipline_code.upper() == code.group().upper()]
    group = re.search(r"\bturma\s+(?:numero\s+|n[º°.]?\s*)?(\d{3,})\b", text)
    if group:
        records = [(item, name) for item, name in records
                   if item.group_sequence == group.group(1)]
    courses = {item.course for item, _ in records}
    matching_courses = [course for course in courses if _plain(course) in text]
    if len(matching_courses) == 1:
        records = [(item, name) for item, name in records
                   if item.course == matching_courses[0]]
    # "em 2026.2", "2026/2": o periodo pedido na propria pergunta.
    periodo = re.search(r"(?<![\d.])(20\d{2})[.\-/](\d)(?!\d)", text)
    if periodo:
        alvo = f"{periodo.group(1)}.{periodo.group(2)}"
        records = [(item, name) for item, name in records if item.semester == alvo]
    if not records:
        return "Não encontrei tempo de estudo importado para esse recorte nas suas disciplinas."

    # Somar semestres diferentes num numero so seria juntar turmas que nunca
    # existiram juntas: a mesma matricula aparece nos dois, e o "total da turma"
    # sairia inflado sem nada na resposta dizendo isso. Com mais de um periodo
    # no recorte, cada um responde por si.
    periodos = sorted({item.semester for item, _ in records}, reverse=True)
    if len(periodos) > 1:
        return "\n\n".join(
            _resposta_de_um_periodo(
                [(item, name) for item, name in records if item.semester == atual],
                text,
                atual,
            )
            for atual in periodos
        )
    return _resposta_de_um_periodo(records, text, periodos[0])


def _resposta_de_um_periodo(records: list, text: str, semester: str) -> str:
    """Total, ranking e distribuicao de um unico periodo."""
    total = sum(item.minutes for item, _ in records)
    linked = sum(bool(item.student_id) for item, _ in records)
    pending = len(records) - linked
    by_student: dict[str, tuple[str, int]] = {}
    for item, name in records:
        if name and item.student_id:
            prior = by_student.get(item.student_id, (name, 0))
            by_student[item.student_id] = (name, prior[1] + item.minutes)
    ranking = sorted(by_student.values(), key=lambda pair: (-pair[1], pair[0]))[:10]
    lines = [f"- {name}: {minutes} min ({minutes / 60:.1f} h)"
             for name, minutes in ranking]
    headline = (f"Período {semester} — tempo de estudo importado: {total} minutos "
                f"({total / 60:.1f} horas) em {len(records)} registros; "
                f"{linked} com aluno cadastrado e {pending} sem aluno no cadastro. "
                f"Média por registro: {total / len(records):.1f} minutos.")
    breakdown_field = None
    if "por disciplina" in text:
        breakdown_field = "discipline_code"
    elif "por turma" in text:
        breakdown_field = "group_sequence"
    elif "por curso" in text:
        breakdown_field = "course"
    if breakdown_field:
        breakdown: dict[str, int] = defaultdict(int)
        for item, _ in records:
            breakdown[getattr(item, breakdown_field)] += item.minutes
        lines = [f"- {label}: {minutes} min ({minutes / 60:.1f} h)"
                 for label, minutes in sorted(breakdown.items(),
                   key=lambda pair: (-pair[1], pair[0]))]
        return headline + "\nDistribuição:\n" + "\n".join(lines[:20])
    if re.search(r"\b(aluno|alunos|ranking|maior|top)\b", text) and lines:
        return headline + "\nAlunos vinculados com mais tempo:\n" + "\n".join(lines)
    return headline
