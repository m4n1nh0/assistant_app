"""Leitura e conciliacao de tempo de estudo exportado em XLSX."""

from __future__ import annotations

from io import BytesIO
from collections import Counter

from openpyxl import load_workbook
from sqlalchemy import select

from ..core.database import DisciplineModel, StudentModel, StudyTimeModel

HEADERS = (
    "CURSO", "COD_DISCIPLINA", "NUM_SEQ_TURMA", "MATRICULA",
    "ANO_ENTRADA", "TEMPO DE ESTUDO (MINUTOS)",
)


async def owned_discipline_scope(db, tutor_id: str) -> set[str]:
    """Codigos de disciplina cadastrados para este professor."""
    disciplines = (await db.execute(select(DisciplineModel).where(
        DisciplineModel.tutor_id == tutor_id
    ))).scalars().all()
    return {item.code.strip().upper()
            for item in disciplines if item.code and item.code.strip()}


def belongs_to_scope(code: str, scope: set[str]) -> bool:
    return code.strip().upper() in scope


async def purge_outside_scope(db, tutor_id: str, scope: set[str]) -> int:
    """Remove registros que a importacao antiga aceitou sem conferir disciplina."""
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    removed = 0
    for item in existing:
        if not belongs_to_scope(item.discipline_code, scope):
            await db.delete(item)
            removed += 1
    if removed:
        await db.commit()
    return removed


def parse_study_time_xlsx(content: bytes) -> tuple[list[dict], list[dict]]:
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
    blank_rows: list[dict] = []
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
        if raw_minutes is None or str(raw_minutes).strip() == "":
            blank_rows.append(dict(discipline_code=code, semester=semester))
            continue
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
    return result, blank_rows


def match_study_student(row: dict, by_enrollment: dict[str, list[StudentModel]]) -> StudentModel | None:
    matches = by_enrollment.get(row["enrollment"], [])
    if len(matches) > 1:
        matches = [student for student in matches
                   if student.class_group == row["group_sequence"]]
    return matches[0] if len(matches) == 1 else None


async def student_enrollment_index(db, tutor_id: str) -> dict[str, list[StudentModel]]:
    students = (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == tutor_id
    ))).scalars().all()
    by_enrollment: dict[str, list[StudentModel]] = {}
    for student in students:
        if student.external_id:
            by_enrollment.setdefault(student.external_id.strip(), []).append(student)
    return by_enrollment


async def preview_study_times(db, tutor_id: str, rows: list[dict]) -> dict:
    by_enrollment = await student_enrollment_index(db, tutor_id)
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    keys = {(item.semester, item.discipline_code, item.group_sequence,
             item.enrollment) for item in existing}
    matched = [row for row in rows if match_study_student(row, by_enrollment)]
    existing_by_key = {(item.semester, item.discipline_code, item.group_sequence,
                        item.enrollment): item for item in existing}
    existing_without_student = sum(
        (row["semester"], row["discipline_code"], row["group_sequence"],
         row["enrollment"]) in existing_by_key
        for row in rows if match_study_student(row, by_enrollment) is None)
    return dict(
        with_registered_student=len(matched),
        without_registered_student=len(rows) - len(matched),
        existing_rows_removed_by_default=existing_without_student,
        new=sum((row["semester"], row["discipline_code"],
                 row["group_sequence"], row["enrollment"]) not in keys for row in rows),
        corrections=sum((row["semester"], row["discipline_code"],
                         row["group_sequence"], row["enrollment"]) in keys for row in rows),
        new_with_student=sum((row["semester"], row["discipline_code"],
                              row["group_sequence"], row["enrollment"]) not in keys
                             for row in matched),
        corrections_with_student=sum((row["semester"], row["discipline_code"],
                                      row["group_sequence"], row["enrollment"]) in keys
                                     for row in matched),
        by_period=dict(sorted(Counter(row["semester"] for row in rows).items())),
        by_discipline=dict(sorted(Counter(row["discipline_code"] for row in rows).items())),
    )


async def remove_unmatched_existing(db, tutor_id: str, rows: list[dict]) -> int:
    """Apaga apenas chaves da planilha que o professor decidiu não guardar."""
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    keys = {(row["semester"], row["discipline_code"], row["group_sequence"],
             row["enrollment"]) for row in rows}
    removed = 0
    for item in existing:
        key = (item.semester, item.discipline_code,
               item.group_sequence, item.enrollment)
        if key in keys:
            await db.delete(item)
            removed += 1
    await db.flush()
    return removed


async def import_study_times(db, tutor_id: str, rows: list[dict]) -> dict:
    by_enrollment = await student_enrollment_index(db, tutor_id)
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
        student = match_study_student(row, by_enrollment)
        item.student_id = student.id if student else None
        linked += bool(item.student_id)
        pending += not bool(item.student_id)
    await db.commit()
    return dict(created=created, updated=updated, linked=linked, pending=pending)
