"""Material por turma: o professor escolhe quais turmas da disciplina o veem no portal."""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    ClassGroupModel,
    MaterialChunkModel,
    MaterialImprovementModel,
    MaterialModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/c.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (MaterialModel, MaterialChunkModel, MaterialImprovementModel,
                          ClassGroupModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                ClassGroupModel(id="c1", tutor_id="t1", code="3001", discipline_id="d1",
                                discipline="BD", semester="2026.2"),
                ClassGroupModel(id="c2", tutor_id="t1", code="3002", discipline_id="d1",
                                discipline="BD", semester="2026.2"),
                ClassGroupModel(id="c-outra", tutor_id="t1", code="9", discipline_id="d2",
                                discipline="Outra", semester="2026.2"),
                ClassGroupModel(id="c-alheia", tutor_id="t2", code="1", discipline_id="d1",
                                discipline="BD", semester="2026.2"),
                MaterialModel(id="m1", tutor_id="t1", discipline_id="d1", discipline="BD",
                              title="Apostila", filename="a.pdf", content="x"),
                MaterialModel(id="m-sem", tutor_id="t1", discipline_id=None, discipline="",
                              title="Solto", filename="s.pdf", content="x"),
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
        yield client
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_material_nasce_para_a_disciplina_toda(api):
    itens = {item["id"]: item for item in api.get("/education/materials").json()}

    assert itens["m1"]["class_ids"] == []


@pytest.mark.integration
def test_escolhe_as_turmas_e_a_lista_devolve(api):
    resposta = api.put("/education/materials/m1/classes", json={"class_ids": ["c2", "c1", "c2"]})

    assert resposta.status_code == 200 and resposta.json()["class_ids"] == ["c1", "c2"]
    itens = {item["id"]: item for item in api.get("/education/materials").json()}
    assert itens["m1"]["class_ids"] == ["c1", "c2"]


@pytest.mark.integration
def test_lista_vazia_volta_a_valer_a_disciplina_toda(api):
    api.put("/education/materials/m1/classes", json={"class_ids": ["c1"]})

    resposta = api.put("/education/materials/m1/classes", json={"class_ids": []})

    assert resposta.json()["class_ids"] == []


@pytest.mark.integration
@pytest.mark.parametrize("turma", ["c-outra", "c-alheia", "nao-existe"])
def test_turma_de_outra_disciplina_ou_de_outro_professor_e_recusada(api, turma):
    resposta = api.put("/education/materials/m1/classes", json={"class_ids": [turma]})

    assert resposta.status_code == 422
    assert api.get("/education/materials").json()[0]["class_ids"] == []


@pytest.mark.integration
def test_material_sem_disciplina_nao_aceita_turma(api):
    resposta = api.put("/education/materials/m-sem/classes", json={"class_ids": ["c1"]})

    assert resposta.status_code == 422


@pytest.mark.integration
def test_material_inexistente_da_404(api):
    assert api.put("/education/materials/nao/classes", json={"class_ids": []}).status_code == 404
