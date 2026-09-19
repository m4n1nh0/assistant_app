"""Limpeza em lote do banco de questoes.

Apagar varias de uma vez e conveniencia, nao permissao nova: questao de quiz ja
aplicado continua sendo arquivada, porque existe resposta de aluno apontando
para ela e o relatorio da turma precisa continuar fechando. Estes testes
existem para que a versao em lote nao afrouxe a regra da versao individual.
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
                LessonModel(id="l1", tutor_id="t1",
                            discipline="ARA0040 - BANCO DE DADOS"),
                QuizModel(id="rascunho", tutor_id="t1", lesson_id="l1", titulo="Rascunho",
                          status="draft", total_questoes=2),
                QuizModel(id="aplicado", tutor_id="t1", lesson_id="l1", titulo="Aplicado",
                          status="open", total_questoes=1),
                QuizModel(id="de-outro", tutor_id="t2", lesson_id="l1", titulo="De outro",
                          status="draft", total_questoes=1),
                QuestionModel(id="q1", quiz_id="rascunho", tipo="multipla",
                              enunciado="Rascunho 1"),
                QuestionModel(id="q2", quiz_id="rascunho", tipo="multipla",
                              enunciado="Rascunho 2"),
                QuestionModel(id="q3", quiz_id="aplicado", tipo="multipla",
                              enunciado="Ja respondida pela turma"),
                QuestionModel(id="q4", quiz_id="de-outro", tipo="multipla",
                              enunciado="De outro professor"),
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
        test_client.sessions = sessions
        yield test_client
    asyncio.run(engine.dispose())


def existentes(client) -> set[str]:
    async def ler():
        async with client.sessions() as db:
            from sqlalchemy import select
            return {row.id for row in (
                await db.execute(select(QuestionModel))).scalars().all()}

    return asyncio.run(ler())


def apagar(client, ids):
    return client.post("/education/quiz/questions/bulk-delete", json={"ids": ids})


def test_rascunho_some_e_aplicada_e_arquivada(client):
    resposta = apagar(client, ["q1", "q2", "q3"])

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"deleted": 2, "archived": 1, "ignored": 0}
    assert existentes(client) == {"q3", "q4"}, "a respondida continua no banco"

    banco = client.get("/education/quiz/questions",
                       params={"include_archived": True}).json()
    arquivada = next(item for item in banco["questions"] if item["id"] == "q3")
    assert arquivada["arquivada"] is True


def test_questao_de_outro_professor_e_ignorada(client):
    resposta = apagar(client, ["q4"])

    assert resposta.json() == {"deleted": 0, "archived": 0, "ignored": 1}
    assert "q4" in existentes(client)


def test_id_repetido_conta_uma_vez_so(client):
    assert apagar(client, ["q1", "q1"]).json() == {
        "deleted": 1, "archived": 0, "ignored": 0}


def test_lista_vazia_nao_faz_nada(client):
    assert apagar(client, []).json() == {"deleted": 0, "archived": 0, "ignored": 0}
    assert len(existentes(client)) == 4


def test_contador_do_quiz_acompanha_o_que_saiu(client):
    apagar(client, ["q1", "q2"])

    async def ler():
        async with client.sessions() as db:
            return (await db.get(QuizModel, "rascunho")).total_questoes

    assert asyncio.run(ler()) == 0


def test_filtro_de_status_traz_so_os_rascunhos(client):
    rascunhos = client.get("/education/quiz/questions",
                           params={"status": "draft"}).json()

    assert {item["id"] for item in rascunhos["questions"]} == {"q1", "q2"}
    assert rascunhos["total"] == 2


def test_listagem_devolve_os_ids_do_filtro_inteiro(client):
    """"Selecionar todos" precisa alcancar o que a paginacao esconde."""
    pagina = client.get("/education/quiz/questions",
                        params={"status": "draft", "limit": 1}).json()

    assert len(pagina["questions"]) == 1
    assert set(pagina["all_ids"]) == {"q1", "q2"}
