"""Aula reunida: o grupo mistura alunos de mais de uma turma (3002 + 3030, segunda).

Falha que isto evita: com um grupo preso a uma unica turma, os alunos da outra turma da
mesma aula nao eram achados no cadastro ("nome nao reconhecido") e os grupos misturados
nao apareciam no filtro de nenhuma das duas turmas.
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
    ProjectGroupPointModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    ProjectGroupNameResolutionModel,
    QuizGroupConfigModel,
    QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education, group_draw
from app.services import project_group_service as pgs

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    DisciplineModel, ClassGroupModel, ClassScheduleModel, StudentModel,
    ProjectGroupModel, ProjectGroupClassModel, ProjectGroupPointModel,
    ProjectGroupMemberModel,
    ProjectGroupNameResolutionModel, GroupDrawModel, GroupDrawEntryModel,
    QuizGroupConfigModel, QuizGroupLinkModel, QuizGroupRepresentativeModel,
)

# Os grupos da segunda misturam alunos da 3002 (Kaic) e da 3030 (Marta).
LISTA_SEGUNDA = """Grupos turma segunda:
GRUPO 1
- Kaic Vinicius
- Marta Souza

GRUPO 2
- Igor Alan
"""


def aluno(id_, nome, turma, matricula):
    return StudentModel(
        id=id_, tutor_id="t1", name=nome, class_id=turma, class_group="x",
        discipline="BANCO DE DADOS", external_id=matricula, active=True,
    )


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/c.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0040", name="BANCO DE DADOS", semester="2026.2"),
                ClassGroupModel(id="c-3002", tutor_id="t1", code="3002", name="A", discipline_id="d1", discipline="BANCO DE DADOS"),
                ClassGroupModel(id="c-3030", tutor_id="t1", code="3030", name="B", discipline_id="d1", discipline="BANCO DE DADOS"),
                ClassGroupModel(id="c-3001", tutor_id="t1", code="3001", name="C", discipline_id="d1", discipline="BANCO DE DADOS"),
                ClassScheduleModel(class_group_id="c-3002", weekday=0, start_time="19:00"),
                ClassScheduleModel(class_group_id="c-3030", weekday=0, start_time="19:00"),
                ClassScheduleModel(class_group_id="c-3001", weekday=3, start_time="19:00"),
                aluno("s-kaic", "Kaic Vinicius", "c-3002", "20240001"),
                aluno("s-igor", "Igor Alan", "c-3002", "20240002"),
                aluno("s-marta", "Marta Souza", "c-3030", "20240003"),
                aluno("s-bruno", "Bruno Teixeira", "c-3001", "20240004"),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.include_router(group_draw.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def corpo(texto, turmas):
    return {"discipline_id": "d1", "text": texto, "class_ids": turmas}


def importar(api, texto, turmas):
    dados = corpo(texto, turmas)
    previa = api.post("/education/project-groups/preview", json=dados)
    assert previa.status_code == 200, previa.text
    resposta = api.post(
        "/education/project-groups/import",
        json={**dados, "preview_sha256": previa.json()["preview_sha256"]},
    )
    assert resposta.status_code == 200, resposta.text
    return previa.json(), resposta.json()


def grupos(api, **params):
    resposta = api.get("/education/project-groups", params=params)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def por_nome(lista):
    return {item["name"]: item for item in lista}


def test_importar_nas_duas_turmas_liga_alunos_de_ambas(api):
    previa, resultado = importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])

    assert previa["roster_count"] == 3
    assert previa["names_without_unique_match"] == 0
    assert resultado["linked_members"] == 3
    grupo1 = por_nome(grupos(api))["GRUPO 1"]
    ligados = {m["name"]: m["student_id"] for m in grupo1["members"]}
    assert ligados == {"Kaic Vinicius": "s-kaic", "Marta Souza": "s-marta"}


def test_com_so_uma_turma_a_aluna_da_outra_nao_e_achada(api):
    previa = api.post("/education/project-groups/preview",
                      json=corpo(LISTA_SEGUNDA, ["c-3002"])).json()

    assert previa["names_without_unique_match"] == 1


def test_previa_traz_as_turmas_juntas(api):
    previa, _ = importar(api, LISTA_SEGUNDA, ["c-3030", "c-3002"])

    assert previa["class_ids"] == ["c-3002", "c-3030"]
    assert previa["class_label"].count(" + ") == 1
    assert "3002" in previa["class_label"] and "3030" in previa["class_label"]


def test_aceita_class_id_antigo_e_junta_com_class_ids(api):
    dados = {"discipline_id": "d1", "text": LISTA_SEGUNDA,
             "class_id": "c-3002", "class_ids": ["c-3030"]}
    previa = api.post("/education/project-groups/preview", json=dados).json()

    assert previa["class_ids"] == ["c-3002", "c-3030"]


def test_grupo_misturado_aparece_no_filtro_das_duas_turmas(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])

    assert len(grupos(api, class_id="c-3002")) == 2
    assert len(grupos(api, class_id="c-3030")) == 2
    assert grupos(api, class_id="c-3001") == []
    assert grupos(api, class_id="none") == []


def test_lista_devolve_turmas_dias_e_rotulo_do_grupo(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])

    grupo = por_nome(grupos(api))["GRUPO 1"]

    assert grupo["class_ids"] == ["c-3002", "c-3030"]
    assert grupo["class_id"] == "c-3002"
    assert grupo["class_days"] == ["segunda"]
    assert "3002" in grupo["class_label"] and "3030" in grupo["class_label"]


def test_reimportar_as_mesmas_turmas_atualiza_sem_duplicar(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    previa, resultado = importar(api, LISTA_SEGUNDA, ["c-3030", "c-3002"])

    assert previa["updated_groups"] == 2 and previa["new_groups"] == 0
    assert resultado["created"] == 0 and resultado["updated"] == 2
    assert len(grupos(api)) == 2


def test_lista_de_uma_turma_so_nao_mexe_nos_grupos_da_aula_reunida(api):
    """A lista da quinta tem "GRUPO 1" tambem: nao pode trocar o da segunda reunida."""
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    importar(api, "GRUPO 1\n- Bruno Teixeira\n", ["c-3001"])

    todos = grupos(api)
    assert len(todos) == 3
    reunido = next(g for g in todos if g["class_ids"] == ["c-3002", "c-3030"] and g["name"] == "GRUPO 1")
    assert {m["name"] for m in reunido["members"]} == {"Kaic Vinicius", "Marta Souza"}


def test_lista_so_de_uma_das_turmas_atualiza_o_grupo_misto_sem_encolher_as_turmas(api):
    """GRUPO 1 de 3002+3030 e uma lista so da 3002: e o mesmo grupo, nao um novo."""
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    dados = corpo("GRUPO 1\n- Kaic Vinicius\n- Igor Alan\n", ["c-3002"])

    previa = api.post("/education/project-groups/preview", json=dados).json()
    assert previa["conflicting_names"] == []
    assert previa["updated_groups"] == 1 and previa["new_groups"] == 0
    assert previa["adjusted_groups"] == []

    resposta = api.post("/education/project-groups/import", json={
        **dados, "preview_sha256": previa["preview_sha256"]})
    assert resposta.status_code == 200, resposta.text
    todos = grupos(api)
    assert len(todos) == 2
    grupo1 = por_nome(todos)["GRUPO 1"]
    assert grupo1["class_ids"] == ["c-3002", "c-3030"]
    assert {m["name"] for m in grupo1["members"]} == {"Kaic Vinicius", "Igor Alan"}


def test_lista_de_mais_turmas_atualiza_o_grupo_e_amplia_as_turmas(api):
    """GRUPO 1 so da 3002 que agora tem gente da 3030: a lista e das duas turmas."""
    importar(api, "GRUPO 1\n- Kaic Vinicius\n", ["c-3002"])
    antes = por_nome(grupos(api))["GRUPO 1"]
    assert antes["class_ids"] == ["c-3002"]

    previa, resultado = importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])

    assert previa["conflicting_names"] == []
    assert previa["updated_groups"] == 1 and previa["new_groups"] == 1  # GRUPO 2 e novo
    ajuste = previa["adjusted_groups"]
    assert [item["name"] for item in ajuste] == ["GRUPO 1"]
    assert ajuste[0]["class_ids_before"] == ["c-3002"]
    assert ajuste[0]["class_ids_after"] == ["c-3002", "c-3030"]
    assert "3002" in ajuste[0]["before_label"]
    assert "3002" in ajuste[0]["after_label"] and "3030" in ajuste[0]["after_label"]
    assert resultado["created"] == 1 and resultado["updated"] == 1

    todos = grupos(api)
    assert len(todos) == 2
    grupo1 = por_nome(todos)["GRUPO 1"]
    assert grupo1["id"] == antes["id"]
    assert grupo1["class_ids"] == ["c-3002", "c-3030"]
    assert {m["name"] for m in grupo1["members"]} == {"Kaic Vinicius", "Marta Souza"}
    # Passa a aparecer tambem no filtro da 3030.
    assert {g["name"] for g in grupos(api, class_id="c-3030")} == {"GRUPO 1", "GRUPO 2"}


def test_ampliar_as_turmas_mantem_os_vinculos_e_o_banco_nao_reclama(api):
    importar(api, "GRUPO 1\n- Kaic Vinicius\n", ["c-3002"])
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])  # e de novo: atualiza igual

    grupo1 = por_nome(grupos(api))["GRUPO 1"]
    ligados = {m["name"]: m["student_id"] for m in grupo1["members"]}
    assert ligados == {"Kaic Vinicius": "s-kaic", "Marta Souza": "s-marta"}
    assert len(grupos(api)) == 2


def test_turmas_que_se_cruzam_so_em_parte_continuam_ambiguas(api):
    """3002+3030 existe; a lista e 3030+quinta: nao da para saber se e o mesmo grupo."""
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    dados = corpo("GRUPO 1\n- Bruno Teixeira\n", ["c-3030", "c-3001"])

    previa = api.post("/education/project-groups/preview", json=dados).json()
    assert previa["conflicting_names"] == ["GRUPO 1"]
    assert previa["new_groups"] == 0 and previa["updated_groups"] == 0

    resposta = api.post("/education/project-groups/import", json={
        **dados, "preview_sha256": previa["preview_sha256"]})
    assert resposta.status_code == 422
    assert "GRUPO 1" in resposta.json()["detail"]
    assert len(grupos(api)) == 2


def test_dois_grupos_com_o_mesmo_nome_nas_turmas_da_lista_sao_ambiguos(api):
    async def semear():
        async with api.sessions() as db:
            for id_, turma in (("gx1", "c-3002"), ("gx2", "c-3030")):
                db.add(ProjectGroupModel(id=id_, tutor_id="t1", discipline_id="d1",
                                         semester="2026.2", name="GRUPO 9", class_id=turma))
            await db.commit()
    asyncio.run(semear())

    previa = api.post("/education/project-groups/preview", json=corpo(
        "GRUPO 9\n- Kaic Vinicius\n", ["c-3002", "c-3030"])).json()

    assert previa["conflicting_names"] == ["GRUPO 9"]


def test_lista_sem_turma_nao_casa_com_grupo_de_turma(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])

    previa, _ = importar(api, "GRUPO 1\n- Kaic Vinicius\n", [])

    assert previa["updated_groups"] == 0 and previa["new_groups"] == 1
    assert len(grupos(api)) == 3


def test_ajuste_so_acontece_ao_confirmar(api):
    """A previa mostra o ajuste, mas as turmas do grupo so mudam no cadastro."""
    importar(api, "GRUPO 1\n- Kaic Vinicius\n", ["c-3002"])

    api.post("/education/project-groups/preview", json=corpo(LISTA_SEGUNDA, ["c-3002", "c-3030"]))

    assert por_nome(grupos(api))["GRUPO 1"]["class_ids"] == ["c-3002"]


def test_atribuir_varias_turmas_a_grupos_sem_turma(api):
    async def semear():
        async with api.sessions() as db:
            db.add_all([
                ProjectGroupModel(id="g1", tutor_id="t1", discipline_id="d1",
                                  semester="2026.2", name="GRUPO 1"),
                ProjectGroupModel(id="g2", tutor_id="t1", discipline_id="d1",
                                  semester="2026.2", name="GRUPO 2"),
            ])
            await db.commit()
    asyncio.run(semear())

    resposta = api.post("/education/project-groups/assign-class", json={
        "group_ids": ["g1", "g2"], "class_ids": ["c-3030", "c-3002"]})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["class_ids"] == ["c-3002", "c-3030"]
    assert all(g["class_ids"] == ["c-3002", "c-3030"] for g in grupos(api))
    assert len(grupos(api, class_id="c-3030")) == 2


def test_atribuir_recusa_nome_que_ja_existe_em_turma_cruzada(api):
    importar(api, "GRUPO 1\n- Igor Alan\n", ["c-3002"])

    async def semear():
        async with api.sessions() as db:
            db.add(ProjectGroupModel(id="g9", tutor_id="t1", discipline_id="d1",
                                     semester="2026.2", name="GRUPO 1"))
            await db.commit()
    asyncio.run(semear())

    resposta = api.post("/education/project-groups/assign-class", json={
        "group_ids": ["g9"], "class_ids": ["c-3002", "c-3030"]})

    assert resposta.status_code == 409
    assert "GRUPO 1" in resposta.json()["detail"]


def test_soltar_a_turma_apaga_as_ligacoes_extras(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    ids = [g["id"] for g in grupos(api)]

    resposta = api.post("/education/project-groups/assign-class", json={
        "group_ids": ids, "class_ids": []})

    assert resposta.status_code == 200, resposta.text
    assert all(g["class_ids"] == [] for g in grupos(api))

    async def linhas():
        async with api.sessions() as db:
            return (await db.execute(select(ProjectGroupClassModel))).scalars().all()
    assert asyncio.run(linhas()) == []


def test_apagar_o_grupo_apaga_as_ligacoes_de_turma(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    grupo = por_nome(grupos(api))["GRUPO 1"]

    assert api.delete(f"/education/project-groups/{grupo['id']}").status_code == 200

    async def linhas():
        async with api.sessions() as db:
            return (await db.execute(select(ProjectGroupClassModel))).scalars().all()
    restantes = asyncio.run(linhas())
    assert {linha.group_id for linha in restantes} == {por_nome(grupos(api))["GRUPO 2"]["id"]}


def test_apagar_todos_limpa_as_ligacoes_de_turma(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])

    assert api.delete("/education/project-groups/all").status_code == 200

    async def linhas():
        async with api.sessions() as db:
            return (await db.execute(select(ProjectGroupClassModel))).scalars().all()
    assert asyncio.run(linhas()) == []


def test_turma_de_outra_disciplina_e_recusada(api):
    async def semear():
        async with api.sessions() as db:
            db.add(ClassGroupModel(id="c-x", tutor_id="t1", code="1", name="X",
                                   discipline_id="d9", discipline="OUTRA"))
            await db.commit()
    asyncio.run(semear())

    resposta = api.post("/education/project-groups/preview",
                        json=corpo(LISTA_SEGUNDA, ["c-3002", "c-x"]))

    assert resposta.status_code == 422


def test_sugestao_de_vinculo_usa_os_alunos_das_turmas_juntas(api):
    async def semear():
        async with api.sessions() as db:
            await db.execute(ProjectGroupModel.__table__.insert().values(
                id="g1", tutor_id="t1", discipline_id="d1", semester="2026.2",
                name="GRUPO 1", class_id="c-3002"))
            await db.execute(ProjectGroupClassModel.__table__.insert().values(
                id="l1", group_id="g1", class_id="c-3002"))
            await db.execute(ProjectGroupClassModel.__table__.insert().values(
                id="l2", group_id="g1", class_id="c-3030"))
            db.add(ProjectGroupMemberModel(group_id="g1", name="Marta Sousa", position=0))
            await db.commit()
    asyncio.run(semear())

    resposta = api.get("/education/project-groups/link-suggestions",
                       params={"discipline_id": "d1"})

    assert resposta.status_code == 200, resposta.text
    candidatos = resposta.json()[0]["candidates"]
    assert candidatos and candidatos[0]["student_id"] == "s-marta"


def test_sorteio_de_uma_das_turmas_inclui_o_grupo_misturado(api):
    importar(api, LISTA_SEGUNDA, ["c-3002", "c-3030"])
    importar(api, "GRUPO 5\n- Bruno Teixeira\n", ["c-3001"])

    esperados = {g["id"] for g in grupos(api, class_id="c-3030")}

    resposta = api.post("/education/group-draws", json={
        "discipline_id": "d1", "class_id": "c-3030", "mode": "fila"})

    assert resposta.status_code == 200, resposta.text
    assert len(esperados) == 2
    assert {item["group_id"] for item in resposta.json()["entries"]} == esperados


def test_helpers_de_turma_aceitam_um_varios_ou_nenhum():
    assert pgs.as_class_list(None) == []
    assert pgs.as_class_list("b") == ["b"]
    assert pgs.as_class_list(["b", "", "a", "b", None]) == ["a", "b"]


def _semear_grupos_soltos(api):
    """GRUPO 1 mistura 3002 e 3030, GRUPO 2 so 3002, GRUPO 3 so 3001, GRUPO 4 sem vinculo."""
    async def semear():
        async with api.sessions() as db:
            for id_, nome in (("g1", "GRUPO 1"), ("g2", "GRUPO 2"),
                              ("g3", "GRUPO 3"), ("g4", "GRUPO 4")):
                db.add(ProjectGroupModel(id=id_, tutor_id="t1", discipline_id="d1",
                                         semester="2026.2", name=nome))
            await db.flush()
            db.add_all([
                ProjectGroupMemberModel(group_id="g1", name="Kaic", student_id="s-kaic", position=0),
                ProjectGroupMemberModel(group_id="g1", name="Marta", student_id="s-marta", position=1),
                ProjectGroupMemberModel(group_id="g2", name="Igor", student_id="s-igor", position=0),
                ProjectGroupMemberModel(group_id="g3", name="Bruno", student_id="s-bruno", position=0),
                ProjectGroupMemberModel(group_id="g4", name="Sem vinculo", position=0),
            ])
            await db.commit()
    asyncio.run(semear())


def test_deduz_a_turma_dos_grupos_pelos_alunos_vinculados(api):
    _semear_grupos_soltos(api)

    resposta = api.post("/education/project-groups/infer-classes",
                        json={"discipline_id": "d1"})

    assert resposta.status_code == 200, resposta.text
    corpo_ = resposta.json()
    assert corpo_["assigned"] == 3
    assert corpo_["without_linked_members"] == ["GRUPO 4"]
    por = por_nome(grupos(api))
    assert por["GRUPO 1"]["class_ids"] == ["c-3002", "c-3030"]
    assert por["GRUPO 2"]["class_ids"] == ["c-3002"]
    assert por["GRUPO 3"]["class_ids"] == ["c-3001"]
    assert por["GRUPO 4"]["class_ids"] == []
    # Passa a aparecer no filtro de cada turma do grupo.
    assert {g["name"] for g in grupos(api, class_id="c-3030")} == {"GRUPO 1"}


def test_deduzir_nao_mexe_em_grupo_que_ja_tem_turma(api):
    _semear_grupos_soltos(api)
    api.post("/education/project-groups/assign-class",
             json={"group_ids": ["g2"], "class_ids": ["c-3030"]})

    api.post("/education/project-groups/infer-classes", json={"discipline_id": "d1"})

    assert por_nome(grupos(api))["GRUPO 2"]["class_ids"] == ["c-3030"]


def test_deduzir_respeita_a_lista_de_grupos_pedida(api):
    _semear_grupos_soltos(api)

    resposta = api.post("/education/project-groups/infer-classes",
                        json={"discipline_id": "d1", "group_ids": ["g3"]})

    assert resposta.json()["assigned"] == 1
    por = por_nome(grupos(api))
    assert por["GRUPO 3"]["class_ids"] == ["c-3001"]
    assert por["GRUPO 1"]["class_ids"] == []


def test_deduzir_deixa_de_fora_nome_que_cruza_com_grupo_existente(api):
    _semear_grupos_soltos(api)
    # Ja existe um GRUPO 2 da 3002 (importado), que cruza com o GRUPO 2 solto.
    importar(api, "GRUPO 2\n- Igor Alan\n", ["c-3002"])

    resposta = api.post("/education/project-groups/infer-classes",
                        json={"discipline_id": "d1"})

    assert resposta.json()["conflicting"] == ["GRUPO 2"]
    soltos = [g for g in grupos(api) if g["name"] == "GRUPO 2" and not g["class_ids"]]
    assert len(soltos) == 1


def test_deduzir_valida_a_disciplina(api):
    resposta = api.post("/education/project-groups/infer-classes",
                        json={"discipline_id": "inexistente"})

    assert resposta.status_code == 404
