"""Pontos lançados ao grupo de projeto, com histórico.

Falha que isto evita: o grupo só tinha um número de "subtração de pontos" e a nota do
projeto. Não havia onde registrar que o grupo ganhou ponto, por quê e quando, nem como
fazer esse ponto chegar a cada integrante.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    ClassGroupModel,
    ClassScheduleModel,
    DisciplineModel,
    LessonModel,
    LessonPointModel,
    ProjectGroupClassModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    ProjectGroupNameResolutionModel,
    ProjectGroupPointModel,
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education
from app.services import group_points_service as points_service

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    DisciplineModel, ClassGroupModel, ClassScheduleModel, StudentModel,
    ProjectGroupModel, ProjectGroupClassModel, ProjectGroupMemberModel,
    ProjectGroupNameResolutionModel, ProjectGroupPointModel, LessonPointModel,
    LessonModel,
)


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/p.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0058", name="CLOUD", semester="2026.2"),
                ClassGroupModel(id="c1", tutor_id="t1", code="3001", name="A", discipline_id="d1", discipline="CLOUD"),
                StudentModel(id="s-ana", tutor_id="t1", name="ANA SOUZA SANTOS", class_id="c1", class_group="3001", external_id="1", active=True),
                StudentModel(id="s-bia", tutor_id="t1", name="BIA LIMA", class_id="c1", class_group="3001", external_id="2", active=True),
                ProjectGroupModel(id="g1", tutor_id="t1", discipline_id="d1", semester="2026.2", name="GRUPO 1", class_id="c1"),
                ProjectGroupModel(id="g2", tutor_id="t1", discipline_id="d1", semester="2026.2", name="GRUPO 2", class_id="c1"),
                ProjectGroupModel(id="g-alheio", tutor_id="t2", discipline_id="d9", semester="2026.2", name="GRUPO X"),
                # GRUPO 1: Ana e Bia ligadas, Caio sem vinculo.
                ProjectGroupMemberModel(id="m-ana", group_id="g1", student_id="s-ana", name="Ana Souza", position=0),
                ProjectGroupMemberModel(id="m-bia", group_id="g1", student_id="s-bia", name="Bia Lima", position=1),
                ProjectGroupMemberModel(id="m-caio", group_id="g1", name="Caio Reis", position=2),
                ProjectGroupMemberModel(id="m-davi", group_id="g2", student_id="s-ana", name="Davi", position=0),
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
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def run(api, fn):
    async def go():
        async with api.sessions() as db:
            return await fn(db)
    return asyncio.run(go())


def lancar(api, grupo="g1", **corpo):
    return api.post(f"/education/project-groups/{grupo}/points", json=corpo)


def historico(api, grupo="g1"):
    resposta = api.get(f"/education/project-groups/{grupo}/points")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def creditos(api):
    async def consultar(db):
        return [
            (item.student_id, item.points, item.source, item.discipline, item.reason)
            for item in (await db.execute(
                select(LessonPointModel).order_by(LessonPointModel.student_name))).scalars().all()
        ]
    return run(api, consultar)


# --- lançar -------------------------------------------------------------------------


def test_lanca_pontos_ao_grupo_com_motivo(api):
    resposta = lancar(api, points=1.5, reason="Melhor  apresentação")

    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["points"] == 1.5
    assert dados["reason"] == "Melhor apresentação"  # espacos repetidos colapsados
    assert dados["credit_members"] is False and dados["credited_count"] == 0
    assert dados["group_total"] == 1.5
    assert historico(api)["total"] == 1.5
    assert creditos(api) == []


def test_o_total_e_a_soma_dos_lancamentos_e_negativo_tira(api):
    lancar(api, points=2, reason="a")
    lancar(api, points=1, reason="b")
    ultimo = lancar(api, points=-0.5, reason="atraso na entrega").json()

    assert ultimo["group_total"] == 2.5
    dados = historico(api)
    assert dados["total"] == 2.5
    assert [item["points"] for item in dados["entries"]].count(-0.5) == 1


def test_lista_vem_do_mais_recente_para_o_mais_antigo(api):
    agora = datetime.now(timezone.utc)
    lancar(api, points=1, reason="antigo", entry_date=(agora - timedelta(days=3)).isoformat())
    lancar(api, points=2, reason="novo", entry_date=agora.isoformat())
    lancar(api, points=3, reason="meio", entry_date=(agora - timedelta(days=1)).isoformat())

    assert [item["reason"] for item in historico(api)["entries"]] == ["novo", "meio", "antigo"]


@pytest.mark.parametrize("corpo", [
    {"points": 0},
    {"points": 101},
    {"points": -101},
    {"points": "muito"},
    {"reason": "sem pontos"},
    {"points": 1, "reason": "x" * 501},
])
def test_recusa_valor_invalido(api, corpo):
    assert lancar(api, **corpo).status_code == 422
    assert historico(api)["entries"] == []


def test_motivo_e_opcional(api):
    resposta = lancar(api, points=1)

    assert resposta.status_code == 200
    assert resposta.json()["reason"] == ""


def test_grupo_inexistente_ou_de_outro_professor(api):
    assert lancar(api, grupo="nao-existe", points=1).status_code == 404
    assert lancar(api, grupo="g-alheio", points=1).status_code == 404
    assert api.get("/education/project-groups/g-alheio/points").status_code == 404


# --- creditar aos integrantes --------------------------------------------------------


def test_credita_cada_integrante_ligado_a_um_aluno(api):
    resposta = lancar(api, points=1, reason="Melhor ideia", credit_members=True)

    dados = resposta.json()
    assert dados["credit_members"] is True and dados["credited_count"] == 2
    assert dados["credit"] == {"credited": 2, "without_link": 1, "members": 3}
    assert "2 integrante(s)" in dados["message"] and "1 sem aluno vinculado" in dados["message"]
    assert creditos(api) == [
        ("s-ana", 1.0, "group", "ARA0058 - CLOUD", "GRUPO 1: Melhor ideia"),
        ("s-bia", 1.0, "group", "ARA0058 - CLOUD", "GRUPO 1: Melhor ideia"),
    ]


def test_o_ponto_creditado_aparece_no_relatorio_de_pontuacoes(api):
    lancar(api, points=1, reason="Melhor ideia", credit_members=True)

    relatorio = api.get("/education/points").json()

    assert relatorio["total_points"] == 2
    nomes = {item["student_name"]: item for item in relatorio["students"]}
    assert set(nomes) == {"ANA SOUZA SANTOS", "BIA LIMA"}
    assert nomes["BIA LIMA"]["discipline"] == "ARA0058 - CLOUD"
    assert nomes["BIA LIMA"]["class_group"] == "3001"


def test_so_o_grupo_nao_mexe_na_pontuacao_dos_alunos(api):
    lancar(api, points=1, credit_members=False)

    assert creditos(api) == []
    assert api.get("/education/points").json()["total_points"] == 0


def test_aluno_em_dois_integrantes_do_mesmo_grupo_recebe_uma_vez(api):
    async def duplicar(db):
        db.add(ProjectGroupMemberModel(id="m-ana2", group_id="g1", student_id="s-ana",
                                       name="Ana S.", position=3))
        await db.commit()
    run(api, duplicar)

    dados = lancar(api, points=1, credit_members=True).json()

    assert dados["credited_count"] == 2
    assert len(creditos(api)) == 2


def test_grupo_sem_ninguem_vinculado_credita_zero_e_avisa(api):
    async def desligar(db):
        for id_ in ("m-ana", "m-bia"):
            (await db.get(ProjectGroupMemberModel, id_)).student_id = None
        await db.commit()
    run(api, desligar)

    dados = lancar(api, points=1, credit_members=True).json()

    assert dados["credited_count"] == 0 and dados["credit"]["without_link"] == 3
    assert creditos(api) == []


def test_pontos_negativos_tambem_podem_ser_creditados(api):
    lancar(api, points=-1, reason="faltou entregar", credit_members=True)

    assert [item[1] for item in creditos(api)] == [-1.0, -1.0]


# --- corrigir e apagar ---------------------------------------------------------------


def test_corrigir_pontos_e_motivo_refaz_o_que_foi_creditado(api):
    entrada = lancar(api, points=1, reason="inicial", credit_members=True).json()

    resposta = api.patch(f"/education/project-groups/g1/points/{entrada['id']}",
                         json={"points": 2.5, "reason": "corrigido"})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["points"] == 2.5 and resposta.json()["group_total"] == 2.5
    assert [(i[1], i[4]) for i in creditos(api)] == [
        (2.5, "GRUPO 1: corrigido"), (2.5, "GRUPO 1: corrigido")]


def test_corrigir_para_so_o_grupo_tira_o_credito_dos_alunos(api):
    entrada = lancar(api, points=1, credit_members=True).json()

    resposta = api.patch(f"/education/project-groups/g1/points/{entrada['id']}",
                         json={"credit_members": False})

    assert resposta.json()["credited_count"] == 0
    assert creditos(api) == []
    assert historico(api)["total"] == 1


def test_corrigir_para_creditar_cria_os_creditos(api):
    entrada = lancar(api, points=1).json()

    api.patch(f"/education/project-groups/g1/points/{entrada['id']}",
              json={"credit_members": True})

    assert len(creditos(api)) == 2


def test_corrigir_so_o_motivo_nao_duplica_creditos(api):
    entrada = lancar(api, points=1, credit_members=True).json()

    api.patch(f"/education/project-groups/g1/points/{entrada['id']}", json={"reason": "novo"})
    api.patch(f"/education/project-groups/g1/points/{entrada['id']}", json={"reason": "outro"})

    assert len(creditos(api)) == 2


def test_corrigir_a_data_leva_a_data_dos_creditos(api):
    entrada = lancar(api, points=1, credit_members=True).json()
    data = "2026-09-01T12:00:00+00:00"

    api.patch(f"/education/project-groups/g1/points/{entrada['id']}", json={"entry_date": data})

    async def datas(db):
        return {item.lesson_date.date().isoformat() for item in
                (await db.execute(select(LessonPointModel))).scalars().all()}
    assert run(api, datas) == {"2026-09-01"}


def test_corrigir_recusa_zero_e_lancamento_de_outro_grupo(api):
    entrada = lancar(api, points=1).json()

    assert api.patch(f"/education/project-groups/g1/points/{entrada['id']}",
                     json={"points": 0}).status_code == 422
    # O lancamento e do g1: pelo g2 nao se acha.
    assert api.patch(f"/education/project-groups/g2/points/{entrada['id']}",
                     json={"points": 1}).status_code == 404
    assert api.patch("/education/project-groups/g1/points/nao-existe",
                     json={"points": 1}).status_code == 404


def test_apagar_o_lancamento_tira_o_total_e_os_creditos(api):
    mantido = lancar(api, points=1, reason="fica", credit_members=True).json()
    apagado = lancar(api, points=3, reason="sai", credit_members=True).json()

    resposta = api.delete(f"/education/project-groups/g1/points/{apagado['id']}")

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["group_total"] == 1 and resposta.json()["credits_removed"] == 2
    assert [item["id"] for item in historico(api)["entries"]] == [mantido["id"]]
    assert [item[1] for item in creditos(api)] == [1.0, 1.0]


def test_apagar_de_outro_grupo_ou_inexistente_da_404(api):
    entrada = lancar(api, points=1).json()

    assert api.delete(f"/education/project-groups/g2/points/{entrada['id']}").status_code == 404
    assert api.delete("/education/project-groups/g1/points/nao-existe").status_code == 404
    assert len(historico(api)["entries"]) == 1


def test_creditos_de_um_lancamento_nao_se_misturam_com_pontos_de_aula(api):
    async def ponto_de_aula(db):
        db.add(LessonPointModel(
            tutor_id="t1", lesson_id="aula-1", student_id="s-ana", student_name="ANA SOUZA SANTOS",
            points=0.5, discipline="ARA0058 - CLOUD", lesson_date=datetime.now(timezone.utc),
            source="extracted"))
        await db.commit()
    run(api, ponto_de_aula)
    entrada = lancar(api, points=1, credit_members=True).json()

    api.delete(f"/education/project-groups/g1/points/{entrada['id']}")

    assert [(i[0], i[1], i[2]) for i in creditos(api)] == [("s-ana", 0.5, "extracted")]


# --- lista de grupos e apagar grupo --------------------------------------------------


def test_lista_de_grupos_traz_total_e_quantidade_de_lancamentos(api):
    lancar(api, points=2, reason="a")
    lancar(api, points=-0.5, reason="b")
    lancar(api, grupo="g2", points=1, reason="c")

    grupos = {g["name"]: g for g in api.get("/education/project-groups").json()}

    assert grupos["GRUPO 1"]["points_total"] == 1.5 and grupos["GRUPO 1"]["points_count"] == 2
    assert grupos["GRUPO 2"]["points_total"] == 1 and grupos["GRUPO 2"]["points_count"] == 1


def test_grupo_sem_lancamento_tem_total_zero(api):
    grupo = next(g for g in api.get("/education/project-groups").json() if g["name"] == "GRUPO 2")

    assert grupo["points_total"] == 0 and grupo["points_count"] == 0


def test_apagar_o_grupo_apaga_os_lancamentos_e_os_creditos(api):
    lancar(api, points=1, credit_members=True)
    lancar(api, grupo="g2", points=2, reason="do g2", credit_members=True)

    assert api.delete("/education/project-groups/g1").status_code == 200

    async def restante(db):
        return [item.group_id for item in
                (await db.execute(select(ProjectGroupPointModel))).scalars().all()]
    assert run(api, restante) == ["g2"]
    assert [(i[0], i[1]) for i in creditos(api)] == [("s-ana", 2.0)]


def test_apagar_todos_os_grupos_limpa_lancamentos_e_creditos(api):
    lancar(api, points=1, credit_members=True)
    lancar(api, grupo="g2", points=2, credit_members=True)

    assert api.delete("/education/project-groups/all").status_code == 200

    async def contar(db):
        return (len((await db.execute(select(ProjectGroupPointModel))).scalars().all()),
                len((await db.execute(select(LessonPointModel))).scalars().all()))
    assert run(api, contar) == (0, 0)


def test_credito_nao_depende_de_aula_existir(api):
    """O ponto creditado nao tem aula: a marca do lancamento ocupa o lugar do id da aula."""
    entrada = lancar(api, points=1, credit_members=True).json()

    async def marcas(db):
        return {item.lesson_id for item in
                (await db.execute(select(LessonPointModel))).scalars().all()}
    assert run(api, marcas) == {points_service.credit_lesson_id(entrada["id"])}
    assert len(points_service.credit_lesson_id(entrada["id"])) <= 64
