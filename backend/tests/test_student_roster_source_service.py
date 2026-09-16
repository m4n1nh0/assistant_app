import io

import pytest
from openpyxl import Workbook

from app.services.student_roster_source_service import preview_student_roster_source


def _pairs(preview):
    enrollment = preview["enrollment_column"]
    name = preview["name_column"]
    return [(row[enrollment], row[name]) for row in preview["rows"]]


@pytest.mark.parametrize("filename,data", [
    ("estacio.csv", "Matrícula;Nome do Aluno;Curso\n"
     "20260123456;JOAO VITOR PEREIRA;ADS\n"
     "20260123457;MARIA EDUARDA SILVA;ADS".encode("utf-8")),
    ("estacio.xml", b"<alunos><aluno><matricula>20260123456</matricula>"
     b"<nome>JOAO VITOR PEREIRA</nome></aluno></alunos>"),
    ("estacio.html", b"<table><tr><th>Matricula</th><th>Nome</th></tr>"
     b"<tr><td>20260123456</td><td>JOAO VITOR PEREIRA</td></tr></table>"),
    ("estacio.txt", b"20260123456 JOAO VITOR PEREIRA\n"
     b"20260123457 MARIA EDUARDA SILVA"),
])
def test_roster_formats_detect_name_and_enrollment(filename, data):
    preview = preview_student_roster_source(data, filename)
    assert _pairs(preview)[0] == ("20260123456", "JOAO VITOR PEREIRA")


def test_copied_estacio_table_and_inferred_numeric_column():
    copied = "Código\tNome do Aluno\tSituação\n"
    copied += "20260123456\tJOAO VITOR PEREIRA\tATIVO\n"
    copied += "20260123457\tMARIA EDUARDA SILVA\tATIVO"
    preview = preview_student_roster_source(pasted_text=copied)
    assert preview["enrollment_column"] == 0
    assert preview["name_column"] == 1
    assert len(preview["rows"]) == 2


def test_source_exposes_class_and_discipline_hints():
    copied = "Matricula;Nome;Turma;Disciplina\n"
    copied += "20260123456;JOAO VITOR PEREIRA;3001;ARA0058\n"
    copied += "20260123457;MARIA EDUARDA SILVA;3001;ARA0058"
    preview = preview_student_roster_source(pasted_text=copied)
    assert preview["class_values"] == ["3001"]
    assert preview["discipline_values"] == ["ARA0058"]


def test_estacio_copied_attendance_report_skips_metadata_and_reads_scope():
    text = """Prof.: MARIANO FLORENCIO MENDONCA\tMatrícula: 14020747
Tipo de Curso\t
11
GRADUAÇÃO
Período Acadêmico\t
2026.3 SEMI
Disciplina\t
ARA0058 - APL. DE CLOUD, IOT E INDÚSTRIA 4.0 EM PYTHON
Turma\t
3008
Data da Aula\t
15/09/2026 - 18:30 - 21:10
Nº\tMatrícula\tAluno\tPresença\tAbono\tBloqueado
1\t202503062862\tALEXSANDRO DE LIMA ARAUJO\t\t\t
2\t202212041702\tGLEDSON NUNES SANTOS\t\t\t
3\t202502188501\tKaua Meneses Leal\t\t\t
"""

    preview = preview_student_roster_source(pasted_text=text)

    assert preview["enrollment_column"] == 1
    assert preview["name_column"] == 2
    assert len(preview["rows"]) == 3
    assert preview["rows"][0][1:3] == ["202503062862", "ALEXSANDRO DE LIMA ARAUJO"]
    assert preview["class_values"] == ["3008"]
    assert preview["discipline_values"] == ["ARA0058"]


def test_xlsx_uses_first_sheet_and_detects_headers():
    workbook = Workbook()
    workbook.active.append(["Matrícula", "Nome", "Turma"])
    workbook.active.append(["20260123456", "JOAO VITOR PEREIRA", "3001"])
    stream = io.BytesIO()
    workbook.save(stream)
    preview = preview_student_roster_source(stream.getvalue(), "alunos.xlsx")
    assert _pairs(preview) == [("20260123456", "JOAO VITOR PEREIRA")]


def test_print_ocr_text_is_reviewed_like_other_sources(monkeypatch):
    from app.services import ocr_service
    monkeypatch.setattr(ocr_service, "is_available", lambda: True)
    monkeypatch.setattr(ocr_service, "text_from_image",
                        lambda _: "20260123456\nJOAO VITOR PEREIRA")
    preview = preview_student_roster_source(b"fake-image", "print.png")
    assert preview["source_type"] == "print (OCR)"
    assert _pairs(preview) == [("20260123456", "JOAO VITOR PEREIRA")]
    assert preview["source_text"]


def test_xml_with_entities_is_rejected():
    with pytest.raises(ValueError, match="DTD"):
        preview_student_roster_source(
            b"<!DOCTYPE alunos [<!ENTITY x 'JOAO'>]><alunos/>", "alunos.xml")
