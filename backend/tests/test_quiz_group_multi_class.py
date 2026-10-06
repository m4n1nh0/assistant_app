"""Quiz em grupo com mais de uma turma (aula reunida: 3002 + 3030, segunda).

Falha que isto evita: o quiz so aceitava uma turma. Escolhendo a 3002, o grupo formado
so por alunos da 3030 ficava de fora, e a matricula de quem e da 3030 nao entrava.
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
    ClassScheduleModel,
    DisciplineModel,
    ProjectGroupClassModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
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
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import quiz_group
from app.services import quiz_group_service as quiz_groups

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    ClassGroupModel, ClassScheduleModel, DisciplineModel, ProjectGroupModel,
    ProjectGroupClassModel, ProjectGroupMemberModel, StudentModel, QuizModel,
    QuestionModel, QuizParticipantModel, StudentAnswerModel, QuestionTranslationModel,
    QuizGroupConfigModel, QuizGroupLinkModel, QuizGroupRepresentativeModel,
    QuizJobModel, QuizSourceModel,
)


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/q.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def aluno(id_, nome, turma, matricula):
        return StudentModel(id=id_, tutor_id="t1", name=nome, class_id=turma,
                            class_group="x", external_id=matricula, active=True)

    def grupo(id_, nome, turmas):
        return ProjectGroupModel(id=id_, tutor_id="t1", discipline_id="d1",
                                 semester="2026.2", name=nome,
                                 class_id=turmas[0] if turmas else None)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0040", name="BANCO DE DADOS", semester="2026.2"),
                ClassGroupModel(id="c-3002", tutor_id="t1", code="3002", name="A", discipline_id="d1", discipline="BD"),
                ClassGroupModel(id="c-3030", tutor_id="t1", code="3030", name="B", discipline_id="d1", discipline="BD"),
                ClassGroupModel(id="c-qui", tutor_id="t1", code="3001", name="Q", discipline_id="d1", discipline="BD"),
                ClassScheduleModel(class_group_id="c-3002", weekday=0, start_time="19:00"),
                ClassScheduleModel(class_group_id="c-3030", weekday=0, start_time="19:00"),
                ClassScheduleModel(class_group_id="c-qui", weekday=3, start_time="19:00"),
                aluno("s-ana", "Ana", "c-3002", "20240001"),
                aluno("s-bia", "Bia", "c-3030", "20240002"),
                aluno("s-caio", "Caio", "c-3030", "20240003"),
                aluno("s-davi", "Davi", "c-qui", "20240004"),
                # G1 mistura 3002+3030; G2 so 3030; G3 so quinta.
                grupo("g1", "GRUPO 1", ["c-3002", "c-3030"]),
                grupo("g2", "GRUPO 2", ["c-3030"]),
                grupo("g3", "GRUPO 3", ["c-qui"]),
                ProjectGroupClassModel(group_id="g1", class_id="c-3002"),
                ProjectGroupClassModel(group_id="g1", class_id="c-3030"),
                ProjectGroupMemberModel(id="m-ana", group_id="g1", student_id="s-ana", name="Ana", position=0),
                ProjectGroupMemberModel(id="m-bia", group_id="g1", student_id="s-bia", name="Bia", position=1),
                ProjectGroupMemberModel(id="m-caio", group_id="g2", student_id="s-caio", name="Caio", position=0),
                ProjectGroupMemberModel(id="m-davi", group_id="g3", student_id="s-davi", name="Davi", position=0),
                QuizModel(id="quiz1", tutor_id="t1", lesson_id="aula", titulo="Quiz", status="draft"),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(quiz_group.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def ligar(api, **extra):
    return api.put("/education/quiz/quiz1/group", json={
        "mode": "media", "discipline_id": "d1", "semester": "2026.2", **extra})


def nomes_dos_grupos(painel):
    return sorted(item["name"] for item in painel["groups"])


def test_duas_turmas_trazem_os_grupos_de_qualquer_uma(api):
    resposta = ligar(api, class_ids=["c-3030", "c-3002"])

    assert resposta.status_code == 200, resposta.text
    painel = resposta.json()
    assert nomes_dos_grupos(painel) == ["GRUPO 1", "GRUPO 2"]
    assert painel["class_ids"] == ["c-3002", "c-3030"]
    assert painel["class_id"] == "c-3002"
    assert " + " in painel["class_label"]
    assert "3002" in painel["class_label"] and "3030" in painel["class_label"]


def test_uma_so_turma_inclui_o_grupo_misturado_mas_nao_o_de_outra(api):
    painel = ligar(api, class_ids=["c-3002"]).json()

    assert nomes_dos_grupos(painel) == ["GRUPO 1"]


def test_class_id_antigo_continua_valendo(api):
    painel = ligar(api, class_id="c-3030").json()

    assert nomes_dos_grupos(painel) == ["GRUPO 1", "GRUPO 2"]
    assert painel["class_ids"] == ["c-3030"]


def test_sem_turma_vale_a_disciplina_toda(api):
    painel = ligar(api).json()

    assert nomes_dos_grupos(painel) == ["GRUPO 1", "GRUPO 2", "GRUPO 3"]
    assert painel["class_ids"] == []


def test_config_antiga_so_com_class_id_e_lida_como_uma_turma(api):
    async def semear():
        async with api.sessions() as db:
            db.add(QuizGroupConfigModel(
                quiz_id="quiz1", tutor_id="t1", mode="media", discipline_id="d1",
                semester="2026.2", class_id="c-qui", seed="s"))
            await db.commit()
    asyncio.run(semear())

    painel = api.get("/education/quiz/quiz1/group").json()

    assert painel["class_ids"] == ["c-qui"]
    assert nomes_dos_grupos(painel) == ["GRUPO 3"]


def test_turma_de_outra_disciplina_ou_inexistente_e_recusada(api):
    async def semear():
        async with api.sessions() as db:
            db.add(ClassGroupModel(id="c-x", tutor_id="t1", code="9", name="X",
                                   discipline_id="d9", discipline="OUTRA"))
            await db.commit()
    asyncio.run(semear())

    assert ligar(api, class_ids=["c-3002", "c-x"]).status_code == 422
    assert ligar(api, class_ids=["nao-existe"]).status_code == 404


def test_turmas_sem_grupo_sao_recusadas(api):
    async def semear():
        async with api.sessions() as db:
            db.add(ClassGroupModel(id="c-vazia", tutor_id="t1", code="7", name="V",
                                   discipline_id="d1", discipline="BD"))
            await db.commit()
    asyncio.run(semear())

    resposta = ligar(api, class_ids=["c-vazia"])

    assert resposta.status_code == 422
    assert "turma" in resposta.json()["detail"].lower()


def test_trocar_as_turmas_limpa_representantes_e_vinculos(api):
    ligar(api, class_ids=["c-3002", "c-3030"])
    api.put("/education/quiz/quiz1/group/representatives/g1", json={"member_id": "m-ana"})

    painel = ligar(api, class_ids=["c-3002"]).json()

    grupo1 = next(item for item in painel["groups"] if item["name"] == "GRUPO 1")
    assert grupo1["representative"] is None


def test_regravar_as_mesmas_turmas_em_outra_ordem_nao_mexe_nos_representantes(api):
    ligar(api, class_ids=["c-3002", "c-3030"])
    api.put("/education/quiz/quiz1/group/representatives/g1", json={"member_id": "m-ana"})

    painel = ligar(api, class_ids=["c-3030", "c-3002"], absence_mode="zero").json()

    grupo1 = next(item for item in painel["groups"] if item["name"] == "GRUPO 1")
    assert grupo1["representative"] is not None


async def _resolver(sessions, turmas, matricula):
    async with sessions() as db:
        config = QuizGroupConfigModel(
            quiz_id="quiz1", tutor_id="t1", mode="media", discipline_id="d1",
            semester="2026.2", class_id=turmas[0], class_ids=",".join(turmas), seed="s")
        return await quiz_groups.resolve_enrollment(db, config, matricula)


def test_matricula_da_segunda_turma_entra_no_grupo_dela(api):
    # Caio e so da 3030 e esta no GRUPO 2, que nao tem a 3002.
    achado = asyncio.run(_resolver(api.sessions, ["c-3002", "c-3030"], "20240003"))
    assert achado.group_name == "GRUPO 2"

    # Com so a 3002 marcada, a matricula dele nao leva a grupo.
    with pytest.raises(quiz_groups.EnrollmentError) as erro:
        asyncio.run(_resolver(api.sessions, ["c-3002"], "20240003"))
    assert erro.value.code == "no_group"


def test_matricula_da_quinta_nao_entra_no_quiz_da_segunda(api):
    with pytest.raises(quiz_groups.EnrollmentError) as erro:
        asyncio.run(_resolver(api.sessions, ["c-3002", "c-3030"], "20240004"))
    assert erro.value.code == "no_group"
