"""Apagar quiz: rascunho sai direto; liberado ou encerrado so com confirmacao.

Falha real: a tela so oferecia DESCARTAR para rascunho, e o servidor recusava o resto -
quiz encerrado ficava na lista para sempre, sem como apagar.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    QuestionModel,
    QuestionTranslationModel,
    QuizGroupConfigModel,
    QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
    QuizJobModel,
    QuizModel,
    QuizParticipantModel,
    QuizSourceModel,
    StudentAnswerModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    QuizModel, QuestionModel, QuizSourceModel, QuizParticipantModel,
    StudentAnswerModel, QuestionTranslationModel, QuizJobModel,
    QuizGroupConfigModel, QuizGroupLinkModel, QuizGroupRepresentativeModel,
)
OPCOES = '[{"label": "A", "texto": "Resposta", "correta": true}]'


def _quiz(id_, status, tutor="t1", phase="lobby"):
    return QuizModel(
        id=id_, tutor_id=tutor, lesson_id="aula", titulo=id_, status=status,
        live_phase=phase, total_questoes=2,
    )


def _pergunta(id_, quiz_id):
    return QuestionModel(
        id=id_, quiz_id=quiz_id, tipo="multipla_escolha", enunciado=f"Pergunta {id_}?",
        opcoes=OPCOES, resposta_correta="A",
    )


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/q.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                _quiz("rascunho", "draft"),
                _quiz("encerrado", "closed"),
                _quiz("ao-vivo", "open", phase="question"),
                _quiz("liberado", "open", phase="lobby"),
                _quiz("alheio", "closed", tutor="t2"),
                _pergunta("r1", "rascunho"),
                _pergunta("e1", "encerrado"), _pergunta("e2", "encerrado"),
                _pergunta("v1", "ao-vivo"),
                _pergunta("l1", "liberado"),
                _pergunta("a1", "alheio"),
                QuizSourceModel(quiz_id="encerrado", source_type="lesson", source_id="aula", label="x"),
                QuizSourceModel(quiz_id="alheio", source_type="lesson", source_id="aula", label="x"),
                QuizParticipantModel(quiz_id="encerrado", attempt_id="t1", student_name="Ana"),
                QuizParticipantModel(quiz_id="encerrado", attempt_id="t2", student_name="Bia"),
                QuizParticipantModel(quiz_id="alheio", attempt_id="t1", student_name="Caio"),
                StudentAnswerModel(question_id="e1", student_name="Ana", resposta="A", correta=True, pontuacao=100),
                StudentAnswerModel(question_id="e1", student_name="Bia", resposta="B", correta=False),
                StudentAnswerModel(question_id="e2", student_name="Ana", resposta="A", correta=True, pontuacao=90),
                StudentAnswerModel(question_id="a1", student_name="Caio", resposta="A", correta=True),
                QuestionTranslationModel(question_id="e1", language="en", enunciado="Question?", opcoes=OPCOES),
                QuestionTranslationModel(question_id="a1", language="en", enunciado="Other?", opcoes=OPCOES),
                QuizJobModel(id="job-encerrado", tutor_id="t1", quiz_id="encerrado", status="done"),
                QuizJobModel(id="job-alheio", tutor_id="t2", quiz_id="alheio", status="done"),
                QuizJobModel(id="job-outro", tutor_id="t1", quiz_id="liberado", status="done"),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def contar(api, model, *criterio):
    async def consulta():
        async with api.sessions() as db:
            return (
                await db.execute(select(func.count()).select_from(model).where(*criterio))
            ).scalar_one()

    return asyncio.run(consulta())


@pytest.mark.integration
def test_rascunho_sai_direto_sem_confirmacao(api):
    resposta = api.delete("/education/quiz/rascunho")

    assert resposta.status_code == 200 and resposta.json()["deleted"] is True
    assert contar(api, QuestionModel, QuestionModel.quiz_id == "rascunho") == 0


@pytest.mark.integration
def test_quiz_encerrado_sem_confirmacao_diz_quanto_seria_perdido(api):
    resposta = api.delete("/education/quiz/encerrado")

    assert resposta.status_code == 409
    detalhe = resposta.json()["detail"]
    assert "2 participante(s)" in detalhe and "3 resposta(s)" in detalhe
    assert api.get("/education/quiz/encerrado").status_code == 200
    assert contar(api, StudentAnswerModel, StudentAnswerModel.question_id.in_(["e1", "e2"])) == 3


@pytest.mark.integration
def test_quiz_encerrado_confirmado_leva_tudo_dele_e_so_dele(api):
    resposta = api.delete("/education/quiz/encerrado", params={"force": "true"})

    assert resposta.status_code == 200
    assert resposta.json() == {"deleted": True, "answers": 3, "participants": 2}
    assert api.get("/education/quiz/encerrado").status_code == 404

    ids = ["e1", "e2"]
    assert contar(api, QuestionModel, QuestionModel.quiz_id == "encerrado") == 0
    assert contar(api, StudentAnswerModel, StudentAnswerModel.question_id.in_(ids)) == 0
    assert contar(api, QuestionTranslationModel, QuestionTranslationModel.question_id.in_(ids)) == 0
    assert contar(api, QuizParticipantModel, QuizParticipantModel.quiz_id == "encerrado") == 0
    assert contar(api, QuizSourceModel, QuizSourceModel.quiz_id == "encerrado") == 0
    assert contar(api, QuizJobModel, QuizJobModel.id == "job-encerrado") == 0


@pytest.mark.integration
def test_apagar_um_quiz_nao_mexe_nos_outros(api):
    api.delete("/education/quiz/encerrado", params={"force": "true"})

    assert contar(api, QuestionModel, QuestionModel.quiz_id == "alheio") == 1
    assert contar(api, StudentAnswerModel, StudentAnswerModel.question_id == "a1") == 1
    assert contar(api, QuestionTranslationModel, QuestionTranslationModel.question_id == "a1") == 1
    assert contar(api, QuizParticipantModel, QuizParticipantModel.quiz_id == "alheio") == 1
    assert contar(api, QuizJobModel, QuizJobModel.id.in_(["job-alheio", "job-outro"])) == 2
    assert api.get("/education/quiz/liberado").status_code == 200


@pytest.mark.integration
def test_quiz_com_pergunta_aberta_para_a_turma_nao_pode_ser_apagado(api):
    for force in ("false", "true"):
        resposta = api.delete("/education/quiz/ao-vivo", params={"force": force})
        assert resposta.status_code == 409
        assert "pergunta aberta" in resposta.json()["detail"]
    assert api.get("/education/quiz/ao-vivo").status_code == 200


@pytest.mark.integration
def test_quiz_liberado_sem_pergunta_aberta_pode_ser_apagado_com_confirmacao(api):
    assert api.delete("/education/quiz/liberado").status_code == 409
    assert api.delete("/education/quiz/liberado", params={"force": "true"}).status_code == 200
    assert contar(api, QuizJobModel, QuizJobModel.id == "job-outro") == 0


@pytest.mark.integration
def test_quiz_de_outro_professor_ou_inexistente_da_404(api):
    for quiz in ("alheio", "nao-existe"):
        resposta = api.delete(f"/education/quiz/{quiz}", params={"force": "true"})
        assert resposta.status_code == 404
    assert contar(api, QuestionModel, QuestionModel.quiz_id == "alheio") == 1
