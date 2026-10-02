"""Renomear e nomear material: o PDF "00001" precisa poder virar um nome reconhecivel."""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import MaterialModel, get_db
from app.core.security import get_current_user
from app.routers import education

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/m.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def material(id_, titulo, tutor="t1"):
        return MaterialModel(
            id=id_, tutor_id=tutor, title=titulo, filename="00001.pdf",
            source_type="pdf", discipline="ARA0040 - BANCO DE DADOS",
            content="texto da apostila", page_count=43, char_count=17, truncated=False,
        )

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(MaterialModel.__table__.create)
        async with sessions() as db:
            db.add_all([material("m1", "00001"), material("alheio", "de outro", "outro")])
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
def test_renomeia_so_o_titulo(api):
    resposta = api.patch("/education/materials/m1", json={"title": "Apostila de Banco de Dados"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["title"] == "Apostila de Banco de Dados"
    assert corpo["filename"] == "00001.pdf"
    assert corpo["discipline"] == "ARA0040 - BANCO DE DADOS"
    assert corpo["page_count"] == 43

    listado = api.get("/education/materials").json()
    assert [item["title"] for item in listado] == ["Apostila de Banco de Dados"]


@pytest.mark.integration
def test_espacos_a_mais_sao_arrumados(api):
    resposta = api.patch("/education/materials/m1", json={"title": "  Banco   de \n Dados  "})

    assert resposta.json()["title"] == "Banco de Dados"


@pytest.mark.integration
@pytest.mark.parametrize("titulo", ["", "   ", "x" * 256])
def test_nome_vazio_ou_longo_demais_e_recusado(api, titulo):
    assert api.patch("/education/materials/m1", json={"title": titulo}).status_code == 422
    assert api.get("/education/materials").json()[0]["title"] == "00001"


@pytest.mark.integration
def test_material_de_outro_professor_ou_inexistente_da_404(api):
    assert api.patch("/education/materials/alheio", json={"title": "meu"}).status_code == 404
    assert api.patch("/education/materials/nao-existe", json={"title": "meu"}).status_code == 404
