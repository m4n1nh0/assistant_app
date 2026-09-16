from app.services.student_roster_agent_service import _json_object, _validated


def test_agent_result_is_validated_and_normalized():
    payload = _json_object('''```json
    {"disciplina":"ara0058 - IoT","turma":"3008","semestre":"2026.3",
     "confidence":0.91,"students":[
       {"matricula":"202503062862","nome":"Alexsandro de Lima Araujo","confidence":0.94},
       {"matricula":"inventada","nome":"Registro inválido","confidence":1}
     ]}
    ```''')

    result = _validated(payload, "gpt")

    assert result["discipline"] == "ARA0058"
    assert result["class_code"] == "3008"
    assert result["confidence"] == .91
    assert result["students"] == [{
        "enrollment": "202503062862",
        "name": "Alexsandro de Lima Araujo",
        "confidence": .94,
    }]


def test_agent_result_without_valid_students_is_rejected():
    assert _validated({"students": [{"matricula": "x", "nome": "Aluno X"}]},
                      "gpt") is None
