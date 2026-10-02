"""Aula e material guardam o nome da disciplina como texto, de lugares diferentes.

Falha real: a aula "MODELAGEM CONCEITUAL" tem disciplina "ARA0040-BANCO DE DADOS" e o
PDF importado, "ARA0040 - BANCO DE DADOS". A tela de gerar quiz lista materiais por
igualdade exata de texto, entao o PDF - 43 paginas, 78 mil caracteres - nunca
aparecia como fonte daquela aula, sem erro nenhum: a lista simplesmente nao o tinha.
"""

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
from app.services.discipline_match import discipline_code, discipline_key, same_discipline

AULA = "ARA0040-BANCO DE DADOS"
MATERIAL = "ARA0040 - BANCO DE DADOS"


@pytest.mark.unit
def test_o_caso_real_aula_e_material_sao_a_mesma_disciplina():
    assert AULA != MATERIAL
    assert same_discipline(AULA, MATERIAL)
    assert same_discipline(MATERIAL, AULA)


@pytest.mark.unit
@pytest.mark.parametrize(
    "a, b",
    [
        ("Banco de Dados", "BANCO DE DADOS"),
        ("Banco de Dados", "banco  de   dados"),
        ("Cálculo I", "calculo i"),
        ("ARA0040 - Banco de Dados", "ARA0040-Banco de Dados"),
        ("ARA 0040 - BANCO DE DADOS", "ARA0040 - BANCO DE DADOS"),
        ("  ARA0040 - BANCO DE DADOS  ", "ARA0040 - BANCO DE DADOS"),
        ("Programação", "PROGRAMACAO"),
    ],
)
def test_grafia_acento_caixa_espaco_e_hifen_nao_separam_a_disciplina(a, b):
    assert same_discipline(a, b)


@pytest.mark.unit
def test_mesmo_codigo_de_curso_e_a_mesma_disciplina_mesmo_com_o_nome_diferente():
    assert same_discipline("ARA0040 - BANCO DE DADOS", "ARA0040 - BD")
    assert same_discipline("ARA0040", "ARA0040-BANCO DE DADOS")


@pytest.mark.unit
@pytest.mark.parametrize(
    "a, b",
    [
        ("ARA0040 - BANCO DE DADOS", "ARA0058 - APL. DE CLOUD, IOT E INDÚSTRIA 4.0 EM PYTHON"),
        ("Banco de Dados", "Banco de Dados Avançado"),
        ("ARA0040", "ARA0041"),
        ("Cálculo I", "Cálculo II"),
    ],
)
def test_disciplinas_diferentes_nao_se_confundem(a, b):
    assert not same_discipline(a, b)


@pytest.mark.unit
@pytest.mark.parametrize("a, b", [("", ""), (None, None), ("", AULA), (AULA, None), ("  ", AULA)])
def test_texto_vazio_nunca_casa_com_nada(a, b):
    assert not same_discipline(a, b)


@pytest.mark.unit
def test_chave_e_codigo():
    assert discipline_key("ARA0040 - Banco de Dados") == "ara0040bancodedados"
    assert discipline_key(None) == ""
    assert discipline_code("ARA0040 - Banco de Dados") == "ara0040"
    assert discipline_code("ENG 101 - Fisica") == "eng101"
    assert discipline_code("Banco de Dados") == ""


# --- a listagem de materiais, que e onde o PDF sumia ----------------------------------

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/m.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def material(id_, titulo, disciplina, tutor="t1", disciplina_id=None):
        return MaterialModel(
            id=id_, tutor_id=tutor, title=titulo, filename=f"{titulo}.pdf",
            source_type="pdf", discipline=disciplina, discipline_id=disciplina_id,
            content="texto", page_count=3, char_count=5, truncated=False,
        )

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(MaterialModel.__table__.create)
        async with sessions() as db:
            db.add_all([
                material("pdf-bd", "00001", MATERIAL, disciplina_id="d-bd"),
                material("pdf-cloud", "apostila", "ARA0058 - APL. DE CLOUD"),
                material("pdf-solto", "sem disciplina", ""),
                material("pdf-alheio", "de outro", MATERIAL, tutor="outro"),
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


def ids(resposta):
    return sorted(item["id"] for item in resposta.json())


@pytest.mark.integration
def test_pdf_importado_aparece_para_a_aula_com_a_grafia_diferente(api):
    """O que o professor via: a aula "ARA0040-BANCO DE DADOS" sem material nenhum."""
    resposta = api.get("/education/materials", params={"discipline": AULA})

    assert resposta.status_code == 200
    assert ids(resposta) == ["pdf-bd"]


@pytest.mark.integration
def test_material_de_outra_disciplina_nao_aparece(api):
    assert ids(api.get("/education/materials", params={"discipline": AULA})) == ["pdf-bd"]
    assert ids(api.get("/education/materials", params={"discipline": "ARA0058-APL. DE CLOUD"})) == ["pdf-cloud"]
    assert ids(api.get("/education/materials", params={"discipline": "Outra coisa"})) == []


@pytest.mark.integration
def test_material_de_outro_professor_nunca_aparece(api):
    assert "pdf-alheio" not in ids(api.get("/education/materials", params={"discipline": AULA}))
    assert "pdf-alheio" not in ids(api.get("/education/materials"))


@pytest.mark.integration
def test_sem_filtro_devolve_todos_do_professor_e_por_id_continua_exato(api):
    assert ids(api.get("/education/materials")) == ["pdf-bd", "pdf-cloud", "pdf-solto"]
    assert ids(api.get("/education/materials", params={"discipline_id": "d-bd"})) == ["pdf-bd"]
    # Com o id, o texto nao entra na comparacao.
    assert ids(api.get(
        "/education/materials", params={"discipline_id": "d-bd", "discipline": "Outra"}
    )) == ["pdf-bd"]


@pytest.mark.integration
def test_material_sem_disciplina_nao_casa_com_aula_nenhuma(api):
    assert "pdf-solto" not in ids(api.get("/education/materials", params={"discipline": AULA}))
