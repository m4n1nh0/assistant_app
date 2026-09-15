from app.services.study_time_query_service import is_study_time_query


def test_study_time_questions_reach_database_query():
    assert is_study_time_query("Qual é o tempo de estudo por disciplina?")
    assert is_study_time_query("Quem tem mais horas de estudo na turma 3001?")
    assert is_study_time_query("Mostre o ranking de minutos de estudo")
    assert is_study_time_query("Quanto os alunos estudaram na turma 3001?")


def test_unrelated_agenda_question_is_not_captured():
    assert not is_study_time_query("Quando tenho aula na turma 3001?")
