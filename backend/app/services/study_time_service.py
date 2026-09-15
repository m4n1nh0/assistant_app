"""Leitura e conciliacao de tempo de estudo exportado em XLSX."""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select

from ..core.database import StudentModel, StudyTimeModel

HEADERS = (
    "CURSO", "COD_DISCIPLINA", "NUM_SEQ_TURMA", "MATRICULA",
    "ANO_ENTRADA", "TEMPO DE ESTUDO (MINUTOS)",
)


def parse_study_time_xlsx(content: bytes) -> list[dict]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    iterator = sheet.values
    header = next(iterator, None)
    if not header:
        raise ValueError("Planilha vazia")
    columns = {str(value or "").strip().upper(): index for index, value in enumerate(header)}
    missing = [name for name in HEADERS if name not in columns]
    if missing:
        raise ValueError("Colunas ausentes: " + ", ".join(missing))
    result = []
    seen = set()
    for line, cells in enumerate(iterator, start=2):
        def cell(name):
            index = columns[name]
            return cells[index] if index < len(cells) else None
        enrollment = str(cell("MATRICULA") or "").strip()
        if not enrollment:
            continue
        code = str(cell("COD_DISCIPLINA") or "").strip().upper()
        group = str(cell("NUM_SEQ_TURMA") or "").strip()
        semester = str(cell("ANO_ENTRADA") or "").strip()
        course = str(cell("CURSO") or "").strip()
        raw_minutes = cell("TEMPO DE ESTUDO (MINUTOS)")
        if not all((code, group, semester, course)):
            raise ValueError(f"Linha {line}: identificacao incompleta")
        try:
            minutes = int(raw_minutes)
            if minutes < 0 or float(raw_minutes) != minutes:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"Linha {line}: minutos invalidos") from None
        key = (semester, code, group, enrollment)
        if key in seen:
            raise ValueError(f"Linha {line}: registro duplicado no arquivo")
        seen.add(key)
        result.append(dict(enrollment=enrollment, discipline_code=code,
                           group_sequence=group, semester=semester,
                           course=course, minutes=minutes))
    if not result:
        raise ValueError("Nenhum registro de tempo de estudo encontrado")
    return result


async def import_study_times(db, tutor_id: str, rows: list[dict]) -> dict:
    students = (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == tutor_id
    ))).scalars().all()
    by_enrollment = {}
    for student in students:
        if student.external_id:
            by_enrollment.setdefault(student.external_id.strip(), []).append(student)
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    by_key = {(item.semester, item.discipline_code, item.group_sequence,
               item.enrollment): item for item in existing}
    created = updated = linked = pending = 0
    for row in rows:
        key = (row["semester"], row["discipline_code"],
               row["group_sequence"], row["enrollment"])
        item = by_key.get(key)
        if item is None:
            item = StudyTimeModel(tutor_id=tutor_id, **row)
            db.add(item)
            by_key[key] = item
            created += 1
        else:
            for field, value in row.items():
                setattr(item, field, value)
            updated += 1
        matches = by_enrollment.get(row["enrollment"], [])
        # Matrícula repetida só é conciliada quando disciplina/turma identificam
        # exatamente um aluno. Sem isso, o dado permanece pendente.
        if len(matches) > 1:
            matches = [s for s in matches if s.class_group == row["group_sequence"]]
        item.student_id = matches[0].id if len(matches) == 1 else None
        linked += bool(item.student_id)
        pending += not bool(item.student_id)
    await db.commit()
    return dict(created=created, updated=updated, linked=linked, pending=pending)
