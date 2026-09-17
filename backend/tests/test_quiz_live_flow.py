"""Fluxo do aluno num quiz ao vivo, do QR Code ao ranking.

Os dois defeitos que estes testes guardam vieram de aula real:

- a tela do aluno parava em "Resposta registrada". A pagina vinha de um POST e
  se atualizava sozinha; recarregar pagina de POST faz o navegador pedir
  confirmacao de reenvio, e a atualizacao nao acontecia;
- o lobby mostrava "Participantes: 0" com a turma dentro, porque so contava
  quem ja tinha respondido.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    QuestionModel,
    QuizModel,
    QuizParticipantModel,
    StudentAnswerModel,
    get_db,
)
from app.routers import quiz_play, quiz_websocket

pytestmark = pytest.mark.integration

QUIZ = "quiz-ao-vivo"
BASE = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
OPCOES = '[{"label": "A", "texto": "3FN", "correta": true}, {"label": "B", "texto": "1FN", "correta": false}]'


@pytest.fixture
def sala():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/quiz.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, StudentAnswerModel, QuizParticipantModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                QuizModel(id=QUIZ, tutor_id="t1", lesson_id="l1", titulo="Modelagem",
                          status="open", live_phase="lobby", total_questoes=2),
                QuestionModel(id="p1", quiz_id=QUIZ, tipo="multipla_escolha",
                              enunciado="Primeira pergunta?", opcoes=OPCOES,
                              resposta_correta="A", created_at=BASE),
                QuestionModel(id="p2", quiz_id=QUIZ, tipo="multipla_escolha",
                              enunciado="Segunda pergunta?", opcoes=OPCOES,
                              resposta_correta="A", created_at=BASE + timedelta(seconds=1)),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(quiz_play.router)
    app.dependency_overrides[get_db] = db_dependency

    def fase(phase, question_id=None):
        async def update():
            async with sessions() as db:
                quiz = await db.get(QuizModel, QUIZ)
                quiz.live_phase = phase
                quiz.current_question_id = question_id
                quiz.question_started_at = datetime.now(timezone.utc) if question_id else None
                await db.commit()
        asyncio.run(update())

    def stats():
        async def read():
            async with sessions() as db:
                return await quiz_websocket.get_quiz_stats(QUIZ, db)
        return asyncio.run(read())

    with TestClient(app) as client:
        client.fase = fase
        client.stats = stats
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


PLAY = f"/education/quiz/{QUIZ}/play?lang=pt"


def entrar(client, nome="Mariano"):
    return client.post(PLAY, data={"student_name": nome}, follow_redirects=False)


def test_entrar_redireciona_para_get_e_aparece_no_lobby(sala):
    assert "ENTRAR NO QUIZ" in sala.get(PLAY).text

    resposta = entrar(sala)

    # POST -> 303 -> GET: a pagina que se recarrega sozinha e sempre a do GET.
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "play?lang=pt"

    espera = sala.get(PLAY)
    assert "Aguardando o professor" in espera.text
    assert 'http-equiv="refresh"' in espera.text

    numeros = sala.stats()
    assert numeros["participants"] == 1
    assert numeros["participants_online"] == 1
    assert numeros["participant_names"] == ["Mariano"]


def test_resposta_registrada_nao_prende_o_aluno_quando_o_professor_avanca(sala):
    entrar(sala)
    sala.fase("question", "p1")
    assert "Primeira pergunta?" in sala.get(PLAY).text

    enviada = sala.post(PLAY, data={"question_id": "p1", "answer": "A"}, follow_redirects=False)
    assert enviada.status_code == 303
    assert "Resposta registrada" in sala.get(PLAY).text

    # Professor avanca: a mesma recarga automatica ja mostra a pergunta nova.
    sala.fase("question", "p2")
    assert "Segunda pergunta?" in sala.get(PLAY).text

    numeros = sala.stats()
    assert numeros["progress"]["total_answers"] == 1
    assert numeros["progress"]["correct"] == 1


def test_resposta_repetida_por_reenvio_nao_conta_duas_vezes(sala):
    entrar(sala)
    sala.fase("question", "p1")

    sala.post(PLAY, data={"question_id": "p1", "answer": "A"})
    sala.post(PLAY, data={"question_id": "p1", "answer": "B"})

    assert sala.stats()["progress"]["total_answers"] == 1


def test_resposta_fora_da_pergunta_atual_nao_e_gravada(sala):
    entrar(sala)
    sala.fase("lobby")

    sala.post(PLAY, data={"question_id": "p1", "answer": "A"})

    assert sala.stats()["progress"]["total_answers"] == 0
    assert "Aguardando o professor" in sala.get(PLAY).text


def test_aluno_que_fechou_a_tela_sai_dos_online_mas_continua_contado(sala):
    entrar(sala, "Ana")

    async def envelhecer():
        async with sala.sessions() as db:
            await db.execute(
                QuizParticipantModel.__table__.update().values(
                    last_seen_at=datetime.now(timezone.utc) - timedelta(minutes=5)
                )
            )
            await db.commit()

    asyncio.run(envelhecer())
    numeros = sala.stats()

    assert numeros["participants"] == 1
    assert numeros["participants_online"] == 0
    assert numeros["participant_names"] == []
