"""Remover um integrante de um grupo de projeto.

Falha que isto evita: o nome cadastrado por engano (ou do aluno que saiu do grupo) so
saia reimportando a lista inteira, e quem tinha sido sorteado como representante, ou
tinha entrado num quiz em grupo, ficava apontando para um integrante que nao existe mais.
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    ClassGroupModel,
    ClassScheduleModel,
    DisciplineModel,
    GroupDrawEntryModel,
    GroupDrawModel,
    ProjectGroupClassModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    ProjectGroupNameResolutionModel,
    QuestionModel,
    QuizGroupConfigModel,
    QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
    QuizModel,
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education, quiz_group

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    DisciplineModel, ClassGroupModel, ClassScheduleModel, StudentModel,
    ProjectGroupModel, ProjectGroupClassModel, ProjectGroupMemberModel,
    ProjectGroupNameResolutionModel, GroupDrawModel, GroupDrawEntryModel,
    QuizModel, QuestionModel, QuizGroupConfigModel, QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
)


def aluno(id_, nome, matricula):
    return StudentModel(id=id_, tutor_id="t1", name=nome, class_id="c1",
                        class_group="x", external_id=matricula, active=True)


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/r.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0040", name="BD", semester="2026.2"),
                ClassGroupModel(id="c1", tutor_id="t1", code="3001", name="A", discipline_id="d1", discipline="BD"),
                aluno("s-ana", "Ana Souza", "20240001"),
                aluno("s-bia", "Bia Lima", "20240002"),
                aluno("s-caio", "Caio Reis", "20240003"),
                aluno("s-davi", "Davi Alves", "20240004"),
                ProjectGroupModel(id="g1", tutor_id="t1", discipline_id="d1", semester="2026.2", name="GRUPO 1", class_id="c1"),
                ProjectGroupModel(id="g2", tutor_id="t1", discipline_id="d1", semester="2026.2", name="GRUPO 2", class_id="c1"),
                ProjectGroupModel(id="g-alheio", tutor_id="t2", discipline_id="d9", semester="2026.2", name="GRUPO X"),
                ProjectGroupMemberModel(id="m-ana", group_id="g1", student_id="s-ana", name="Ana Souza", position=0),
                ProjectGroupMemberModel(id="m-bia", group_id="g1", student_id="s-bia", name="Bia Lima", position=1),
                ProjectGroupMemberModel(id="m-caio", group_id="g1", student_id="s-caio", name="Caio Reis", position=2),
                ProjectGroupMemberModel(id="m-davi", group_id="g2", student_id="s-davi", name="Davi Alves", position=0),
                ProjectGroupMemberModel(id="m-x", group_id="g-alheio", name="Fulano", position=0),
                QuizModel(id="quiz1", tutor_id="t1", lesson_id="aula", titulo="Quiz", status="closed"),
                QuizModel(id="quiz2", tutor_id="t1", lesson_id="aula", titulo="Quiz 2", status="closed"),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.include_router(quiz_group.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def run(api, coro_fn):
    async def go():
        async with api.sessions() as db:
            return await coro_fn(db)
    return asyncio.run(go())


def membros(api, grupo="g1"):
    lista = api.get("/education/project-groups").json()
    return next(g for g in lista if g["id"] == grupo)["members"]


def usar_em_quiz(api):
    """Ana entrou no quiz1 e no quiz2; Bia e a representante do quiz1 e foi sorteada na apresentacao."""
    async def semear(db):
        db.add_all([
            QuizGroupLinkModel(quiz_id="quiz1", attempt_id="a-ana", group_id="g1",
                               group_name="GRUPO 1", member_id="m-ana", member_name="Ana Souza"),
            QuizGroupLinkModel(quiz_id="quiz2", attempt_id="a-ana2", group_id="g1",
                               group_name="GRUPO 1", member_id="m-ana", member_name="Ana Souza"),
            QuizGroupLinkModel(quiz_id="quiz1", attempt_id="a-caio", group_id="g1",
                               group_name="GRUPO 1", member_id="m-caio", member_name="Caio Reis"),
            QuizGroupConfigModel(quiz_id="quiz1", tutor_id="t1", mode="representante",
                                 discipline_id="d1", seed="s"),
            QuizGroupRepresentativeModel(quiz_id="quiz1", group_id="g1", member_id="m-bia",
                                         member_name="Bia Lima"),
            GroupDrawModel(id="d-1", tutor_id="t1", discipline_id="d1", semester="2026.2",
                           seed="x"),
            GroupDrawEntryModel(id="e1", draw_id="d-1", group_id="g1", group_name="GRUPO 1",
                                position=1, representative_member_id="m-bia",
                                representative_name="Bia Lima", representative_round=2),
        ])
        await db.commit()
    run(api, semear)


# --- remover -----------------------------------------------------------------------


def test_remove_o_integrante_e_os_outros_ficam_em_ordem(api):
    resposta = api.delete("/education/project-groups/g1/members/m-ana")

    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["removed"] == "Ana Souza" and dados["remaining"] == 2
    lista = membros(api)
    assert [(m["name"], m["position"]) for m in lista] == [("Bia Lima", 0), ("Caio Reis", 1)]


def test_o_aluno_cadastrado_continua_existindo(api):
    api.delete("/education/project-groups/g1/members/m-ana")

    async def contar(db):
        return (await db.get(StudentModel, "s-ana")).name
    assert run(api, contar) == "Ana Souza"


def test_remover_no_meio_nao_deixa_buraco_nas_posicoes(api):
    api.delete("/education/project-groups/g1/members/m-bia")

    assert [m["position"] for m in membros(api)] == [0, 1]


def test_nao_remove_o_ultimo_integrante(api):
    resposta = api.delete("/education/project-groups/g2/members/m-davi")

    assert resposta.status_code == 409
    assert "apague o grupo" in resposta.json()["detail"]
    assert len(membros(api, "g2")) == 1


def test_remove_ate_sobrar_um_e_ai_recusa(api):
    assert api.delete("/education/project-groups/g1/members/m-ana").status_code == 200
    assert api.delete("/education/project-groups/g1/members/m-bia").status_code == 200

    assert api.delete("/education/project-groups/g1/members/m-caio").status_code == 409
    assert [m["name"] for m in membros(api)] == ["Caio Reis"]


def test_integrante_inexistente_de_outro_grupo_ou_grupo_alheio(api):
    assert api.delete("/education/project-groups/g1/members/nao-existe").status_code == 404
    # m-davi existe, mas e do grupo g2.
    assert api.delete("/education/project-groups/g1/members/m-davi").status_code == 404
    assert len(membros(api, "g2")) == 1
    assert api.delete("/education/project-groups/g-alheio/members/m-x").status_code == 404
    assert api.delete("/education/project-groups/nao-existe/members/m-ana").status_code == 404


# --- o que apontava para ele ---------------------------------------------------------


def test_uso_conta_quizzes_representacao_e_sorteio(api):
    usar_em_quiz(api)

    ana = api.get("/education/project-groups/g1/members/m-ana/usage").json()
    bia = api.get("/education/project-groups/g1/members/m-bia/usage").json()
    davi = api.get("/education/project-groups/g2/members/m-davi/usage").json()

    assert ana["quiz_participations"] == 2 and ana["quiz_representations"] == 0
    assert bia["quiz_representations"] == 1 and bia["draw_representations"] == 1
    assert bia["quiz_participations"] == 0
    assert ana["name"] == "Ana Souza" and ana["members"] == 3 and ana["can_remove"] is True
    assert davi == {"quiz_participations": 0, "quiz_representations": 0,
                    "draw_representations": 0, "name": "Davi Alves",
                    "members": 1, "can_remove": False}


def test_uso_de_integrante_inexistente_ou_de_outro_grupo(api):
    assert api.get("/education/project-groups/g1/members/nao-existe/usage").status_code == 404
    assert api.get("/education/project-groups/g1/members/m-davi/usage").status_code == 404
    assert api.get("/education/project-groups/g-alheio/members/m-x/usage").status_code == 404


def test_remover_desfaz_aparelho_representante_e_sorteio_dele(api):
    usar_em_quiz(api)

    resposta = api.delete("/education/project-groups/g1/members/m-ana")
    assert resposta.json()["cleaned"] == {"quiz_participations": 2,
                                          "quiz_representations": 0,
                                          "draw_representations": 0}
    # Os aparelhos da Ana saem; o do Caio fica.
    assert links_of(api) == [("quiz1", "m-caio")]


def links_of(api):
    async def links(db):
        return [(item.quiz_id, item.member_id) for item in
                (await db.execute(select(QuizGroupLinkModel))).scalars().all()]
    return run(api, links)


def test_remover_o_representante_deixa_o_grupo_sem_representante_e_solta_o_sorteio(api):
    usar_em_quiz(api)

    resposta = api.delete("/education/project-groups/g1/members/m-bia")

    assert resposta.json()["cleaned"]["quiz_representations"] == 1
    assert resposta.json()["cleaned"]["draw_representations"] == 1

    async def estado(db):
        reps = (await db.execute(select(QuizGroupRepresentativeModel))).scalars().all()
        entrada = await db.get(GroupDrawEntryModel, "e1")
        return reps, entrada
    reps, entrada = run(api, estado)
    assert reps == []
    assert entrada.representative_member_id is None and entrada.representative_name == ""
    # A posicao do grupo no sorteio nao muda.
    assert entrada.position == 1

    painel = api.get("/education/quiz/quiz1/group").json()
    grupo1 = next(g for g in painel["groups"] if g["name"] == "GRUPO 1")
    assert grupo1["representative"] is None
    assert [m["name"] for m in grupo1["members"]] == ["Ana Souza", "Caio Reis"]


def test_remover_um_nao_mexe_no_que_aponta_para_outro_grupo(api):
    usar_em_quiz(api)

    api.delete("/education/project-groups/g1/members/m-caio")

    async def contar(db):
        return (
            len((await db.execute(select(QuizGroupRepresentativeModel))).scalars().all()),
            (await db.get(GroupDrawEntryModel, "e1")).representative_member_id,
        )
    assert run(api, contar) == (1, "m-bia")
    assert len(membros(api, "g2")) == 1


def test_reimportar_a_lista_recoloca_o_integrante(api):
    assert api.delete("/education/project-groups/g1/members/m-caio").status_code == 200
    texto = "GRUPO 1\n- Ana Souza\n- Bia Lima\n- Caio Reis\n"
    corpo = {"discipline_id": "d1", "text": texto, "class_ids": ["c1"]}
    previa = api.post("/education/project-groups/preview", json=corpo).json()

    resposta = api.post("/education/project-groups/import",
                        json={**corpo, "preview_sha256": previa["preview_sha256"]})

    assert resposta.status_code == 200, resposta.text
    assert [m["name"] for m in membros(api)] == ["Ana Souza", "Bia Lima", "Caio Reis"]


def test_remover_pode_ser_repetido_sem_quebrar(api):
    assert api.delete("/education/project-groups/g1/members/m-ana").status_code == 200

    assert api.delete("/education/project-groups/g1/members/m-ana").status_code == 404
    assert len(membros(api)) == 2
