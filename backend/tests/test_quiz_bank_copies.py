"""Montar quiz com questoes existentes nao pode inchar o banco de questoes.

A questao escolhida e copiada para o rascunho novo - e proposital, para
corrigir a copia nao mexer no quiz ja aplicado. Mas copia nao e questao nova:
sem separar as duas coisas, cada simulado montado duplicava o banco inteiro, que
foi exatamente o que apareceu em uso.
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    LessonModel,
    MaterialModel,
    QuestionModel,
    QuizModel,
    QuizSourceModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education

pytestmark = pytest.mark.integration

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def client():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/quiz.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, QuizSourceModel,
                          LessonModel, MaterialModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                LessonModel(id="l1", tutor_id="t1", discipline="ARA0040 - BANCO"),
                QuizModel(id="origem", tutor_id="t1", lesson_id="l1",
                          titulo="Quiz da aula", status="open", total_questoes=2),
                QuestionModel(id="q1", quiz_id="origem", tipo="multipla_escolha",
                              enunciado="O que e 1FN?"),
                QuestionModel(id="q2", quiz_id="origem", tipo="multipla_escolha",
                              enunciado="O que e 2FN?"),
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
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


def montar(client, ids, titulo="Simulado"):
    return client.post("/education/quiz/from-questions",
                       json={"titulo": titulo, "question_ids": ids})


def banco(client, **params):
    return client.get("/education/quiz/questions", params=params).json()


def test_montar_quiz_nao_duplica_o_banco(client):
    antes = banco(client)
    assert antes["total"] == 2

    assert montar(client, ["q1", "q2"]).status_code == 201

    depois = banco(client)
    assert depois["total"] == 2, "a copia nao entra como questao nova"
    assert {item["id"] for item in depois["questions"]} == {"q1", "q2"}


def test_a_copia_existe_e_continua_no_quiz_novo(client):
    novo = montar(client, ["q1"]).json()

    questoes = client.get(f"/education/quiz/{novo['id']}").json()["questoes"]
    assert len(questoes) == 1
    assert questoes[0]["enunciado"] == "O que e 1FN?"
    assert questoes[0]["id"] != "q1", "e copia, nao a mesma linha"


def test_original_mostra_em_quantos_quizzes_foi_reaproveitada(client):
    montar(client, ["q1"], titulo="Simulado 1")
    montar(client, ["q1"], titulo="Simulado 2")

    questoes = {item["id"]: item for item in banco(client)["questions"]}
    assert questoes["q1"]["copias"] == 2
    assert questoes["q2"]["copias"] == 0


def test_copia_de_copia_aponta_para_a_raiz(client):
    primeiro = montar(client, ["q1"], titulo="Simulado 1").json()
    copia = client.get(f"/education/quiz/{primeiro['id']}").json()["questoes"][0]

    montar(client, [copia["id"]], titulo="Simulado 2")

    questoes = {item["id"]: item for item in banco(client)["questions"]}
    assert set(questoes) == {"q1", "q2"}, "o banco nao cresce com copia de copia"
    assert questoes["q1"]["copias"] == 2


def test_da_para_ver_as_copias_quando_se_pede(client):
    montar(client, ["q1"])

    com_copias = banco(client, include_copies=True)

    assert com_copias["total"] == 3
