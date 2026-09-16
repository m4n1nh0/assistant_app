"""Regressoes para planilhas mistas e disciplinas de outros professores."""

from io import BytesIO
from types import SimpleNamespace

from openpyxl import Workbook

from app.services.study_time_service import (
    belongs_to_scope, match_study_student, parse_study_time_xlsx,
)


def test_blank_minutes_do_not_turn_into_zero_or_block_valid_rows():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["CURSO", "COD_DISCIPLINA", "NUM_SEQ_TURMA", "MATRICULA",
                  "ANO_ENTRADA", "TEMPO DE ESTUDO (MINUTOS)"])
    sheet.append(["ADS", "ARA0040", 3001, "123", "2026.1", ""])
    sheet.append(["ADS", "ARA0040", 3001, "124", "2026.1", 45])
    content = BytesIO()
    workbook.save(content)

    rows, blank_rows = parse_study_time_xlsx(content.getvalue())

    assert blank_rows == [{"discipline_code": "ARA0040", "semester": "2026.1"}]
    assert [(row["enrollment"], row["minutes"]) for row in rows] == [("124", 45)]


def test_only_registered_code_belongs_to_professor_across_periods():
    scope = {"ARA0040"}

    assert belongs_to_scope("ara0040", scope)
    assert belongs_to_scope("ARA0040", scope)
    assert not belongs_to_scope("ARA0015", scope)


def test_unmatched_enrollment_is_not_assigned_to_another_student():
    row = {"enrollment": "123", "group_sequence": "14500856"}
    student = SimpleNamespace(id="other", class_group="3001")

    assert match_study_student(row, {"456": [student]}) is None
