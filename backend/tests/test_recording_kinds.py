"""Gravacao de aula, de apresentacao de grupo e de palestra.

O mecanismo e o mesmo nos tres casos - gravar, transcrever, resumir, indexar e
virar fonte de quiz. O que muda e a que a gravacao pertence, e e isso que estes
testes fixam: aula precisa de disciplina, apresentacao pertence a um grupo e
herda dele, palestra vive sozinha e se identifica pelo titulo.
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    ClassGroupModel,
    DisciplineModel,
    LessonClassGroupModel,
    LessonModel,
    ProjectGroupModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education

pytestmark = pytest.mark.integration

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def client():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/aulas.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (
                LessonModel, LessonClassGroupModel, ClassGroupModel,
                DisciplineModel, ProjectGroupModel,
            ):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0040",
                                name="BANCO DE DADOS", semester="2026.2", active=True),
                ClassGroupModel(id="c1", tutor_id="t1", discipline_id="d1",
                                discipline="ARA0040 - BANCO DE DADOS", code="3001",
                                name="Turma 3001", semester="2026.2", active=True),
                ProjectGroupModel(id="g1", tutor_id="t1", discipline_id="d1",
                                  semester="2026.2", name="Grupo 4"),
                ProjectGroupModel(id="g2", tutor_id="t2", discipline_id="d1",
                                  semester="2026.2", name="De outro professor"),
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


def criar(client, **body):
    return client.post("/education/lessons", json=body)


def test_aula_continua_exigindo_disciplina(client):
    assert criar(client, kind="aula").status_code == 422

    resposta = criar(client, kind="aula", class_ids=["c1"], title="Normalizacao")

    assert resposta.status_code == 200, resposta.text
    aula = resposta.json()
    assert aula["kind"] == "aula"
    assert aula["discipline"] == "ARA0040 - BANCO DE DADOS"
    assert aula["class_labels"] == ["3001 Turma 3001"]


def test_palestra_dispensa_disciplina_e_turma_mas_exige_titulo(client):
    assert criar(client, kind="palestra").status_code == 422

    palestra = criar(client, kind="palestra", title="LGPD na prática").json()

    assert palestra["kind"] == "palestra"
    assert palestra["title"] == "LGPD na prática"
    assert palestra["discipline"] == ""
    assert palestra["class_labels"] == []


def test_apresentacao_pertence_ao_grupo_e_herda_a_disciplina(client):
    assert criar(client, kind="apresentacao", group_id="nao-existe").status_code == 404
    # Grupo de outro professor não é fonte para esta conta.
    assert criar(client, kind="apresentacao", group_id="g2").status_code == 404

    apresentacao = criar(client, kind="apresentacao", group_id="g1").json()

    assert apresentacao["kind"] == "apresentacao"
    assert apresentacao["group_id"] == "g1"
    assert apresentacao["group_name"] == "Grupo 4"
    assert apresentacao["title"] == "Apresentacao: Grupo 4"
    assert apresentacao["discipline"] == "ARA0040 - BANCO DE DADOS"
    assert apresentacao["semester"] == "2026.2"


def test_listagem_filtra_por_tipo_e_por_grupo(client):
    criar(client, kind="aula", class_ids=["c1"], title="Aula 1")
    criar(client, kind="palestra", title="LGPD na prática")
    criar(client, kind="apresentacao", group_id="g1")

    todas = client.get("/education/lessons").json()
    palestras = client.get("/education/lessons", params={"kind": "palestra"}).json()
    do_grupo = client.get("/education/lessons", params={"group_id": "g1"}).json()

    assert len(todas) == 3
    assert [item["title"] for item in palestras] == ["LGPD na prática"]
    assert [item["group_name"] for item in do_grupo] == ["Grupo 4"]
