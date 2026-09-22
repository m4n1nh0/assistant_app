from app.services.study_time_query_service import is_study_time_query


def test_study_time_questions_reach_database_query():
    assert is_study_time_query("Qual é o tempo de estudo por disciplina?")
    assert is_study_time_query("Quem tem mais horas de estudo na turma 3001?")
    assert is_study_time_query("Mostre o ranking de minutos de estudo")
    assert is_study_time_query("Quanto os alunos estudaram na turma 3001?")


def test_unrelated_agenda_question_is_not_captured():
    assert not is_study_time_query("Quando tenho aula na turma 3001?")


def test_resposta_separa_os_periodos_importados(monkeypatch):
    """Dois semestres nunca viram um total so.

    A mesma matricula aparece nos dois; somada, a resposta diria que a turma
    estudou 12h quando ela estudou 10h num periodo e 2h no outro.
    """
    import asyncio
    from types import SimpleNamespace

    from app.services import study_time_query_service as service

    registros = [
        (SimpleNamespace(semester="2026.2", minutes=600, student_id="s1",
                         discipline_code="ARA0040", group_sequence="15052214",
                         course="ADS"), "Ana"),
        (SimpleNamespace(semester="2026.3", minutes=120, student_id="s1",
                         discipline_code="ARA0040", group_sequence="15052214",
                         course="ADS"), "Ana"),
    ]
    _fake_records(monkeypatch, service, registros)

    resposta = asyncio.run(service.study_time_chat_response("t1", "tempo de estudo"))

    assert "Período 2026.2" in resposta and "600 minutos" in resposta
    assert "Período 2026.3" in resposta and "120 minutos" in resposta
    assert "720 minutos" not in resposta, "a soma dos dois periodos nao pode sair"


def test_pergunta_com_periodo_responde_so_aquele(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.services import study_time_query_service as service

    registros = [
        (SimpleNamespace(semester="2026.2", minutes=600, student_id="s1",
                         discipline_code="ARA0040", group_sequence="15052214",
                         course="ADS"), "Ana"),
        (SimpleNamespace(semester="2026.3", minutes=120, student_id="s1",
                         discipline_code="ARA0040", group_sequence="15052214",
                         course="ADS"), "Ana"),
    ]
    _fake_records(monkeypatch, service, registros)

    resposta = asyncio.run(
        service.study_time_chat_response("t1", "tempo de estudo em 2026.3")
    )

    assert "Período 2026.3" in resposta
    assert "2026.2" not in resposta


def _fake_records(monkeypatch, service, registros):
    """Troca banco e escopo por dados em memoria."""
    class _Result:
        def all(self):
            return registros

    class _Session:
        async def execute(self, *args, **kwargs):
            return _Result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(service, "AsyncSessionLocal", lambda: _Session())

    async def _scope(db, tutor_id):
        return {"ARA0040"}

    monkeypatch.setattr(service, "owned_discipline_scope", _scope)
