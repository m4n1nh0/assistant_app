"""Quando uma pergunta sobre "aula" e agenda, e quando e sobre o que foi dado.

A rota de agenda projeta as proximas semanas a partir dos horarios semanais e
ignora qualquer data citada. Cair nela com "buscar sobre a aula do dia 10/09"
devolvia a lista de aulas futuras no lugar do conteudo da aula pedida.
"""

from datetime import datetime, timezone

import pytest

from app.services.academic_query_service import is_academic_schedule_query

pytestmark = pytest.mark.unit

# Quinta-feira, 17/09/2026, 09:00 em Sao Paulo.
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "message",
    [
        "quando tenho aula?",
        "quais os horarios das minhas turmas",
        "quais as proximas aulas",
        "tenho aula dia 21/09?",
        "liste as datas das aulas de banco de dados",
        "quais os horarios das aulas sobre banco de dados?",
    ],
)
def test_schedule_questions_go_to_the_schedule(message):
    assert is_academic_schedule_query(message, now=NOW) is True


@pytest.mark.parametrize(
    "message",
    [
        "Pode buscar sobre a aula do dia 10/09?",
        "me passe um resumo da aula do dia 09/10",
        "qual foi o conteudo da aula do dia 14/09?",
        "o que foi visto na aula do dia 14/09?",
        "tive aula dia 10/09?",
        "explica a materia da aula de quinta dia 10/09",
    ],
)
def test_questions_about_a_given_class_do_not(message):
    assert is_academic_schedule_query(message, now=NOW) is False


def test_messages_without_class_words_are_not_schedule():
    assert is_academic_schedule_query("qual o dia de hoje?", now=NOW) is False
