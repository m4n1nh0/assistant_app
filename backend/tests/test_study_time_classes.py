"""A turma da planilha nao e a turma do professor.

A instituicao manda a sequencia ("15034853"); em sala a turma se chama "3001".
Nada no arquivo liga uma coisa a outra - quem liga e o aluno, pela matricula.
Estes testes fixam as duas pontas: a listagem devolve as duas turmas, e a previa
da importacao mostra para onde cada sequencia vai antes de gravar.
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
    StudentModel,
    StudyTimeModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education

pytestmark = pytest.mark.integration

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def sessions():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/tempos.db")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (DisciplineModel, ClassGroupModel, StudentModel, StudyTimeModel):
                await conn.run_sync(model.__table__.create)
        async with maker() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0058",
                                name="CLOUD", semester="2026.2", active=True),
                ClassGroupModel(id="c1", tutor_id="t1", discipline_id="d1",
                                code="3001", name="Presencial",
                                discipline="ARA0058 - CLOUD", semester="2026.2"),
                StudentModel(id="s1", tutor_id="t1", name="Gledson", class_id="c1",
                             class_group="3001 Presencial", external_id="202212041702"),
                # Aluno sem turma: a matricula casa, o agrupamento nao.
                StudentModel(id="s2", tutor_id="t1", name="Avulso", class_id=None,
                             external_id="999"),
                StudyTimeModel(id="r1", tutor_id="t1", student_id="s1",
                               enrollment="202212041702", discipline_code="ARA0058",
                               group_sequence="15034853", course="ADS",
                               semester="2026.2", minutes=712),
                StudyTimeModel(id="r2", tutor_id="t1", student_id=None,
                               enrollment="000", discipline_code="ARA0058",
                               group_sequence="15034853", course="ADS",
                               semester="2026.2", minutes=60),
            ])
            await db.commit()

    asyncio.run(seed())
    yield maker
    asyncio.run(engine.dispose())


@pytest.fixture
def client(sessions):
    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as test_client:
        yield test_client


def test_listagem_traz_a_turma_do_cadastro_ao_lado_da_importada(client):
    registros = {item["id"]: item for item in client.get("/education/study-times").json()}

    com_aluno = registros["r1"]
    assert com_aluno["group_sequence"] == "15034853", "a origem continua visivel"
    assert com_aluno["class_code"] == "3001"
    assert com_aluno["class_label"] == "3001 Presencial"

    sem_aluno = registros["r2"]
    assert sem_aluno["group_sequence"] == "15034853"
    assert sem_aluno["class_label"] == "", "sem aluno nao ha turma para agrupar"


def test_previa_mostra_para_onde_cada_sequencia_vai(sessions):
    from app.services.study_time_service import preview_study_times, student_enrollment_index

    async def executar():
        async with sessions() as db:
            indice = await student_enrollment_index(db, "t1")
            return await preview_study_times(db, "t1", [
                {"enrollment": "202212041702", "discipline_code": "ARA0058",
                 "group_sequence": "15034853", "course": "ADS",
                 "semester": "2026.2", "minutes": 712},
                {"enrollment": "999", "discipline_code": "ARA0058",
                 "group_sequence": "15034853", "course": "ADS",
                 "semester": "2026.2", "minutes": 60},
                {"enrollment": "sem-cadastro", "discipline_code": "ARA0058",
                 "group_sequence": "15034854", "course": "ADS",
                 "semester": "2026.2", "minutes": 30},
            ]), indice

    previa, _ = asyncio.run(executar())
    mapeamento = {item["group_sequence"]: item for item in previa["group_mapping"]}

    assert mapeamento["15034853"]["classes"] == [{"label": "3001 Presencial", "rows": 1}]
    assert mapeamento["15034853"]["without_class"] == 1, "o aluno sem turma aparece"
    assert mapeamento["15034853"]["rows"] == 2

    assert mapeamento["15034854"]["classes"] == []
    assert mapeamento["15034854"]["without_class"] == 1
