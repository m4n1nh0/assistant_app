"""Regressoes para planilhas mistas e disciplinas de outros professores."""

from io import BytesIO

from openpyxl import Workbook

from app.services.study_time_service import belongs_to_scope, parse_study_time_xlsx


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


def test_only_registered_code_and_period_belong_to_professor():
    scope = {("ARA0040", "2026.1")}

    assert belongs_to_scope("ara0040", "2026.1", scope)
    assert not belongs_to_scope("ARA0015", "2026.1", scope)
    assert not belongs_to_scope("ARA0040", "2025.2", scope)
