"""Grupos de projeto por turma: a lista da quinta nao pode mexer na da segunda.

Falha que isto evita: o cadastro identificava o grupo pelo nome dentro da disciplina.
Disciplina com duas turmas (segunda e quinta) tem "GRUPO 1" nas duas, e importar a
lista da quinta trocava os integrantes do GRUPO 1 da segunda e apagava os que nao
estavam na lista nova.
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import database
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
from app.services import quiz_group_service as quiz_groups

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    DisciplineModel, ClassGroupModel, ClassScheduleModel, StudentModel,
    ProjectGroupModel, ProjectGroupClassModel, ProjectGroupPointModel,
    ProjectGroupMemberModel,
    ProjectGroupNameResolutionModel, GroupDrawModel, GroupDrawEntryModel, QuizGroupConfigModel, QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
)

LISTA_SEGUNDA = """Grupos turma segunda:
GRUPO 1
- Kaic Vinicius
- Lucas Motta

GRUPO 2
- Igor Alan
"""

LISTA_QUINTA = """Grupos turma quinta:
GRUPO 1
- Bruno Teixeira

GRUPO 2
- Carla Mendes
- Lucas Motta
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
                DisciplineModel(id="d2", tutor_id="t1", code="ARA0058", name="CLOUD", semester="2026.2"),
                ClassGroupModel(id="c-seg", tutor_id="t1", code="3001", name="Segunda", discipline_id="d1", discipline="BANCO DE DADOS"),
                ClassGroupModel(id="c-qui", tutor_id="t1", code="3002", name="Quinta", discipline_id="d1", discipline="BANCO DE DADOS"),
                ClassGroupModel(id="c-cloud", tutor_id="t1", code="4001", name="Cloud", discipline_id="d2", discipline="CLOUD"),
                ClassGroupModel(id="c-alheia", tutor_id="t2", code="9", name="Alheia", discipline_id="d1", discipline="BD"),
                ClassScheduleModel(class_group_id="c-seg", weekday=0, start_time="19:00"),
                ClassScheduleModel(class_group_id="c-qui", weekday=3, start_time="19:00"),
                aluno("s-kaic", "Kaic Vinicius", "c-seg", "20240001"),
                aluno("s-igor", "Igor Alan", "c-seg", "20240002"),
                # Homonimos: mesmo nome nas duas turmas, matriculas diferentes.
                aluno("s-lucas-seg", "Lucas Motta", "c-seg", "20240010"),
                aluno("s-lucas-qui", "Lucas Motta", "c-qui", "20240020"),
                aluno("s-bruno", "Bruno Teixeira", "c-qui", "20240003"),
                aluno("s-carla", "Carla Mendes", "c-qui", "20240004"),
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


def importar(api, texto, classe=None, disciplina="d1"):
    corpo = {"discipline_id": disciplina, "text": texto, "class_id": classe}
    previa = api.post("/education/project-groups/preview", json=corpo)
    assert previa.status_code == 200, previa.text
    resposta = api.post(
        "/education/project-groups/import",
        json={**corpo, "preview_sha256": previa.json()["preview_sha256"]},
    )
    assert resposta.status_code == 200, resposta.text
    return previa.json(), resposta.json()


def grupos(api, **params):
    return api.get("/education/project-groups", params=params).json()


def por_nome(lista):
    return {item["name"]: item for item in lista}


def nomes(grupo):
    return [membro["name"] for membro in grupo["members"]]


# --- importar por turma ---------------------------------------------------------------


@pytest.mark.integration
def test_previa_diz_de_qual_turma_e_dia_a_lista_vai(api):
    previa, _ = importar(api, LISTA_SEGUNDA, "c-seg")

    assert previa["class_id"] == "c-seg"
    assert previa["class_label"] == "3001 Segunda · segunda"


@pytest.mark.integration
def test_importar_a_quinta_nao_mexe_nos_grupos_da_segunda(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    importar(api, LISTA_QUINTA, "c-qui")

    segunda = por_nome(grupos(api, class_id="c-seg"))
    quinta = por_nome(grupos(api, class_id="c-qui"))

    # Os quatro grupos existem, e cada "GRUPO 1" guarda os seus integrantes.
    assert len(grupos(api, discipline_id="d1")) == 4
    assert nomes(segunda["GRUPO 1"]) == ["Kaic Vinicius", "Lucas Motta"]
    assert nomes(segunda["GRUPO 2"]) == ["Igor Alan"]
    assert nomes(quinta["GRUPO 1"]) == ["Bruno Teixeira"]
    assert nomes(quinta["GRUPO 2"]) == ["Carla Mendes", "Lucas Motta"]


@pytest.mark.integration
def test_homonimo_e_ligado_ao_aluno_da_turma_da_lista(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    importar(api, LISTA_QUINTA, "c-qui")

    segunda = por_nome(grupos(api, class_id="c-seg"))
    quinta = por_nome(grupos(api, class_id="c-qui"))
    lucas_seg = next(m for m in segunda["GRUPO 1"]["members"] if m["name"] == "Lucas Motta")
    lucas_qui = next(m for m in quinta["GRUPO 2"]["members"] if m["name"] == "Lucas Motta")

    assert lucas_seg["student_id"] == "s-lucas-seg"
    assert lucas_qui["student_id"] == "s-lucas-qui"


@pytest.mark.integration
def test_reimportar_na_mesma_turma_atualiza_sem_duplicar(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    _, resultado = importar(api, LISTA_SEGUNDA, "c-seg")

    assert resultado["created"] == 0 and resultado["updated"] == 2
    assert len(grupos(api, class_id="c-seg")) == 2


@pytest.mark.integration
def test_lista_sem_turma_nao_encontra_os_grupos_das_turmas(api):
    importar(api, LISTA_SEGUNDA, "c-seg")

    previa, resultado = importar(api, LISTA_QUINTA, None)

    assert previa["new_groups"] == 2 and previa["updated_groups"] == 0
    assert resultado["created"] == 2
    assert nomes(por_nome(grupos(api, class_id="c-seg"))["GRUPO 1"]) == ["Kaic Vinicius", "Lucas Motta"]
    assert len(grupos(api, class_id="none")) == 2


@pytest.mark.integration
def test_turma_invalida_e_recusada(api):
    corpo = {"discipline_id": "d1", "text": LISTA_SEGUNDA}
    assert api.post("/education/project-groups/preview", json={**corpo, "class_id": "nao-existe"}).status_code == 404
    assert api.post("/education/project-groups/preview", json={**corpo, "class_id": "c-alheia"}).status_code == 404
    deoutra = api.post("/education/project-groups/preview", json={**corpo, "class_id": "c-cloud"})
    assert deoutra.status_code == 422 and "não é desta disciplina" in deoutra.json()["detail"]


# --- listar ---------------------------------------------------------------------------


@pytest.mark.integration
def test_lista_traz_a_turma_e_os_dias_de_cada_grupo_e_filtra(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    importar(api, LISTA_QUINTA, "c-qui")

    todos = grupos(api, discipline_id="d1")
    assert {(g["class_label"], tuple(g["class_days"])) for g in todos} == {
        ("3001 Segunda · segunda", ("segunda",)),
        ("3002 Quinta · quinta", ("quinta",)),
    }
    assert {g["class_id"] for g in grupos(api, class_id="c-qui")} == {"c-qui"}
    assert grupos(api, class_id="none") == []


@pytest.mark.integration
def test_turma_com_dois_dias_mostra_os_dois(api):
    async def horarios():
        async with api.sessions() as db:
            db.add(ClassScheduleModel(class_group_id="c-seg", weekday=3, start_time="19:00"))
            await db.commit()

    asyncio.run(horarios())
    importar(api, LISTA_SEGUNDA, "c-seg")

    assert grupos(api)[0]["class_label"] == "3001 Segunda · segunda e quinta"


# --- grupos que ja existiam sem turma -------------------------------------------------


def cadastrar_sem_turma(api):
    importar(api, LISTA_SEGUNDA, None)
    return {item["name"]: item["id"] for item in grupos(api)}


@pytest.mark.integration
def test_atribui_turma_aos_grupos_que_ja_existiam(api):
    ids = cadastrar_sem_turma(api)

    resposta = api.post(
        "/education/project-groups/assign-class",
        json={"group_ids": list(ids.values()), "class_id": "c-seg"},
    )

    assert resposta.status_code == 200 and resposta.json()["assigned"] == 2
    assert {g["class_id"] for g in grupos(api)} == {"c-seg"}
    # Integrantes e vinculos ficam como estavam.
    assert nomes(por_nome(grupos(api))["GRUPO 1"]) == ["Kaic Vinicius", "Lucas Motta"]


@pytest.mark.integration
def test_atribuir_recusa_nome_repetido_no_destino(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    ids = {item["name"]: item["id"] for item in grupos(api, class_id="none")}
    importar(api, LISTA_QUINTA, None)
    sem_turma = {item["name"]: item["id"] for item in grupos(api, class_id="none")}

    resposta = api.post(
        "/education/project-groups/assign-class",
        json={"group_ids": list(sem_turma.values()), "class_id": "c-seg"},
    )

    assert ids == {}
    assert resposta.status_code == 409
    assert "GRUPO 1" in resposta.json()["detail"] and "GRUPO 2" in resposta.json()["detail"]
    assert {g["class_id"] for g in grupos(api, class_id="none")} == {None}


@pytest.mark.integration
def test_atribuir_valida_turma_e_grupos(api):
    ids = list(cadastrar_sem_turma(api).values())
    url = "/education/project-groups/assign-class"

    assert api.post(url, json={"group_ids": ids, "class_id": "c-cloud"}).status_code == 422
    assert api.post(url, json={"group_ids": ids, "class_id": "c-alheia"}).status_code == 404
    assert api.post(url, json={"group_ids": [*ids, "nao-existe"], "class_id": "c-seg"}).status_code == 404
    assert api.post(url, json={"group_ids": [], "class_id": "c-seg"}).status_code == 422


@pytest.mark.integration
def test_atribuir_nao_mistura_disciplinas_e_pode_soltar_a_turma(api):
    ids = list(cadastrar_sem_turma(api).values())
    api.post("/education/project-groups/assign-class", json={"group_ids": ids, "class_id": "c-seg"})

    solto = api.post("/education/project-groups/assign-class", json={"group_ids": ids, "class_id": None})
    assert solto.status_code == 200
    assert {g["class_id"] for g in grupos(api)} == {None}

    async def outra_disciplina():
        async with api.sessions() as db:
            grupo = await db.get(ProjectGroupModel, ids[0])
            grupo.discipline_id = "d2"
            await db.commit()

    asyncio.run(outra_disciplina())
    misturado = api.post("/education/project-groups/assign-class", json={"group_ids": ids, "class_id": None})
    assert misturado.status_code == 422


# --- sugestao de vinculo --------------------------------------------------------------


@pytest.mark.integration
def test_sugestao_de_vinculo_usa_so_os_alunos_da_turma_do_grupo(api):
    async def grupo_sem_vinculo():
        async with api.sessions() as db:
            db.add(ProjectGroupModel(id="g-qui", tutor_id="t1", discipline_id="d1", class_id="c-qui", semester="2026.2", name="GRUPO 9"))
            db.add(ProjectGroupMemberModel(id="m1", group_id="g-qui", name="Lucas Motta", position=0))
            await db.commit()

    asyncio.run(grupo_sem_vinculo())

    sugestoes = api.get("/education/project-groups/link-suggestions", params={"discipline_id": "d1"}).json()

    assert len(sugestoes) == 1
    assert sugestoes[0]["automatic_match"]["student_id"] == "s-lucas-qui"
    assert sugestoes[0]["automatic_match"]["enrollment"] == "20240020"
    assert sugestoes[0]["class_label"] == "3002 Quinta · quinta"


# --- sorteio por turma ----------------------------------------------------------------


@pytest.mark.integration
def test_sorteio_da_turma_so_inclui_os_grupos_dela(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    importar(api, LISTA_QUINTA, "c-qui")
    quinta_ids = {g["id"] for g in grupos(api, class_id="c-qui")}

    resposta = api.post(
        "/education/group-draws",
        json={"discipline_id": "d1", "class_id": "c-qui", "mode": "fila", "per_day": 1},
    )

    sorteio = resposta.json()
    assert resposta.status_code == 200 and sorteio["total"] == 2
    assert {item["group_id"] for item in sorteio["entries"]} == quinta_ids
    assert sorteio["class_id"] == "c-qui"
    assert sorteio["class_label"] == "3002 Quinta · quinta"
    assert "3002 Quinta" in sorteio["title"]


@pytest.mark.integration
def test_sorteio_sem_turma_continua_valendo_para_todos_os_grupos(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    importar(api, LISTA_QUINTA, "c-qui")

    sorteio = api.post("/education/group-draws", json={"discipline_id": "d1"}).json()

    assert sorteio["total"] == 4 and sorteio["class_id"] is None


@pytest.mark.integration
def test_sorteio_recusa_turma_sem_grupos_ou_de_outra_disciplina(api):
    importar(api, LISTA_SEGUNDA, "c-seg")

    vazia = api.post("/education/group-draws", json={"discipline_id": "d1", "class_id": "c-qui"})
    assert vazia.status_code == 422 and "Essa turma nao tem grupos" in vazia.json()["detail"]
    assert api.post("/education/group-draws", json={"discipline_id": "d1", "class_id": "c-cloud"}).status_code == 422
    assert api.post("/education/group-draws", json={"discipline_id": "d1", "class_id": "c-alheia"}).status_code == 404


# --- quiz em grupo por turma ----------------------------------------------------------


def config_do_quiz(turma):
    return QuizGroupConfigModel(
        quiz_id="q1", tutor_id="t1", mode="media", discipline_id="d1",
        class_id=turma, seed="s",
    )


async def resolver(sessions, turma, matricula):
    async with sessions() as db:
        return await quiz_groups.resolve_enrollment(db, config_do_quiz(turma), matricula)


@pytest.mark.integration
def test_matricula_so_vale_na_turma_do_quiz(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    importar(api, LISTA_QUINTA, "c-qui")

    achado = asyncio.run(resolver(api.sessions, "c-seg", "20240001"))  # Kaic, segunda
    assert (achado.group_name, achado.member_name) == ("GRUPO 1", "Kaic Vinicius")

    # Bruno e da quinta: no quiz da segunda a matricula dele nao leva a grupo.
    with pytest.raises(quiz_groups.EnrollmentError) as erro:
        asyncio.run(resolver(api.sessions, "c-seg", "20240003"))
    assert erro.value.code == "no_group"

    # Sem turma no quiz (disciplina toda), as duas turmas entram.
    assert asyncio.run(resolver(api.sessions, None, "20240003")).member_name == "Bruno Teixeira"


@pytest.mark.integration
def test_homonimo_cai_no_grupo_da_propria_turma_no_quiz(api):
    importar(api, LISTA_SEGUNDA, "c-seg")
    importar(api, LISTA_QUINTA, "c-qui")

    seg = asyncio.run(resolver(api.sessions, "c-seg", "20240010"))
    qui = asyncio.run(resolver(api.sessions, "c-qui", "20240020"))

    assert (seg.group_name, qui.group_name) == ("GRUPO 1", "GRUPO 2")


# --- rotulo da turma e banco ----------------------------------------------------------


@pytest.mark.integration
def test_rotulo_da_turma_sem_horario_sai_so_com_o_nome(api):
    async def consultar():
        async with api.sessions() as db:
            return await pgs.class_labels(db, "t1", ["c-cloud", None, "inexistente"])

    assert asyncio.run(consultar()) == {
        "c-cloud": {"label": "4001 Cloud", "days": [], "display": "4001 Cloud"}
    }


@pytest.mark.integration
def test_banco_aceita_o_mesmo_nome_em_turmas_diferentes_mas_nao_na_mesma(api):
    async def gravar(turma, id_):
        async with api.sessions() as db:
            db.add(ProjectGroupModel(
                id=id_, tutor_id="t1", discipline_id="d1", class_id=turma, semester="2026.2", name="GRUPO 1"))
            await db.commit()

    asyncio.run(gravar("c-seg", "a"))
    asyncio.run(gravar("c-qui", "b"))  # outra turma: pode
    with pytest.raises(IntegrityError):
        asyncio.run(gravar("c-seg", "c"))  # mesma turma: nao pode


@pytest.mark.unit
def test_migracao_da_unicidade_nao_quebra_fora_do_mysql():
    """No SQLite a restricao antiga nao sai sem reconstruir a tabela: so avisa."""
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tempfile.mkdtemp()}/m.db")
    with engine.begin() as conn:
        ProjectGroupModel.__table__.create(conn)
        database._scope_project_group_names_by_class(conn)  # nao levanta
        database._scope_project_group_names_by_class(conn)  # repetir e seguro


@pytest.mark.unit
def test_migracao_nao_faz_nada_sem_a_tabela():
    from sqlalchemy import create_engine

    with create_engine(f"sqlite:///{tempfile.mkdtemp()}/n.db").begin() as conn:
        database._scope_project_group_names_by_class(conn)
