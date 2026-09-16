from app.services.project_group_service import (
    build_project_group_chat_action, is_project_group_question,
    parse_project_group_text,
    suggested_student_matches,
)


def test_group_list_preserves_annotations_as_data():
    groups, context = parse_project_group_text(
        "QUIZ SERA O TEMA 2 para 13/10\n"
        "GRUPO 1\nNICOLAS ROSA\nRAIAN LUZ v\n"
        "GRUPO 2 -0,5\nSAIMON RUAM v\nLUIZ FERNANDO\n"
    )

    assert [group["name"] for group in groups] == ["GRUPO 1", "GRUPO 2"]
    assert groups[1]["note"] == "-0,5"
    assert groups[0]["members"][1] == {"name": "RAIAN LUZ", "note": "v"}
    assert context == "QUIZ SERA O TEMA 2 para 13/10"


def test_pasted_chat_list_proposes_import_without_writing():
    action = build_project_group_chat_action(
        "Cadastre os grupos de IoT na ARA0058:\n"
        "GRUPO 1\nNICOLAS ROSA\nGRUPO 2\nRAIAN LUZ"
    )

    assert action is not None
    assert action["type"] == "project_group_import"
    assert action["discipline_code"] == "ARA0058"
    assert action["group_count"] == 2


def test_project_question_requests_registered_group_context():
    assert is_project_group_question("Analise o projeto do grupo 3 da ARA0058")
    assert is_project_group_question("Qual grupo tem Nicolas Rosa?")
    assert not is_project_group_question("Quando tenho aula na turma 3001?")


def test_name_suggestions_show_matriculas_without_linking():
    from types import SimpleNamespace
    roster = [
        SimpleNamespace(id="one", name="JOAO VITOR PEREIRA DA SILVA", external_id="20250001"),
        SimpleNamespace(id="two", name="MARIA EDUARDA SOUZA", external_id="20250002"),
    ]
    candidates = suggested_student_matches("JOAO VITOR PEREIRA", roster)
    assert candidates[0]["student_id"] == "one"
    assert candidates[0]["enrollment"] == "20250001"
    assert all(candidate["student_id"] != "two" for candidate in candidates)
