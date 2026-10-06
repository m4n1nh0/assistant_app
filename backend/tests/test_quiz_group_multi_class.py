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
    MaterialModel,
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
    QuizJobModel, QuizSourceModel, MaterialModel,
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


# --- grupo que apresentou fica de fora (quiz rapido da apresentacao) -----------------


def test_grupo_de_fora_some_do_quiz_e_vem_nomeado_no_painel(api):
    painel = ligar(api, class_ids=["c-3002", "c-3030"], exclude_group_ids=["g1"]).json()

    assert nomes_dos_grupos(painel) == ["GRUPO 2"]
    assert painel["excluded_group_ids"] == ["g1"]
    assert painel["excluded_groups"] == ["GRUPO 1"]


def test_sem_exclusao_o_painel_nao_lista_ninguem_de_fora(api):
    painel = ligar(api, class_ids=["c-3002", "c-3030"]).json()

    assert painel["excluded_group_ids"] == [] and painel["excluded_groups"] == []


def test_grupo_de_fora_inexistente_ou_de_outra_disciplina_e_recusado(api):
    async def semear():
        async with api.sessions() as db:
            db.add(ProjectGroupModel(id="g-outra", tutor_id="t1", discipline_id="d2",
                                     semester="2026.2", name="GRUPO X"))
            await db.commit()
    asyncio.run(semear())

    assert ligar(api, exclude_group_ids=["nao-existe"]).status_code == 404
    assert ligar(api, exclude_group_ids=["g-outra"]).status_code == 404


def test_nao_deixa_de_fora_o_unico_grupo_que_sobraria(api):
    resposta = ligar(api, class_ids=["c-qui"], exclude_group_ids=["g3"])

    assert resposta.status_code == 422
    assert "Não sobra nenhum grupo" in resposta.json()["detail"]


def test_integrante_do_grupo_de_fora_recebe_o_aviso_proprio(api):
    from sqlalchemy import select

    ligar(api, class_ids=["c-3002", "c-3030"], exclude_group_ids=["g1"])

    async def resolver(matricula):
        async with api.sessions() as db:
            config = (await db.execute(select(QuizGroupConfigModel))).scalars().one()
            return await quiz_groups.resolve_enrollment(db, config, matricula)

    # Ana (3002) e Bia (3030) sao do GRUPO 1, que apresentou.
    for matricula in ("20240001", "2024-0002"):
        with pytest.raises(quiz_groups.EnrollmentError) as erro:
            asyncio.run(resolver(matricula))
        assert erro.value.code == "presenter"
    # Caio, do GRUPO 2, joga normalmente.
    assert asyncio.run(resolver("20240003")).group_name == "GRUPO 2"


def test_o_aviso_de_quem_apresentou_existe_nos_tres_idiomas():
    from app.routers import quiz_play

    for idioma in ("pt", "es", "en"):
        assert quiz_play._PUBLIC_TEXT[idioma]["enrollment_presenter"]


def test_mudar_o_grupo_de_fora_limpa_representantes_e_vinculos(api):
    ligar(api, class_ids=["c-3002", "c-3030"])
    api.put("/education/quiz/quiz1/group/representatives/g2", json={"member_id": "m-caio"})

    painel = ligar(api, class_ids=["c-3002", "c-3030"], exclude_group_ids=["g1"]).json()

    grupo2 = next(item for item in painel["groups"] if item["name"] == "GRUPO 2")
    assert grupo2["representative"] is None


def test_depois_que_a_turma_respondeu_nao_muda_o_grupo_de_fora(api, monkeypatch):
    from app.routers import quiz_group as router

    ligar(api, class_ids=["c-3002", "c-3030"])

    async def ja_respondeu(db, quiz_id):
        return 3

    monkeypatch.setattr(router, "_answer_count", ja_respondeu)

    resposta = ligar(api, class_ids=["c-3002", "c-3030"], exclude_group_ids=["g1"])

    assert resposta.status_code == 409
    assert "grupos que ficam de fora" in resposta.json()["detail"]


def test_regravar_so_a_penalidade_continua_valendo_com_grupo_de_fora(api):
    ligar(api, class_ids=["c-3002", "c-3030"], exclude_group_ids=["g1"])

    painel = ligar(api, class_ids=["c-3002", "c-3030"], exclude_group_ids=["g1"],
                   absence_mode="percent", absence_percent=10).json()

    assert painel["absence_mode"] == "percent" and painel["excluded_group_ids"] == ["g1"]


# --- pedido de quiz ja em grupo --------------------------------------------------------


def test_pedido_com_group_setup_sobrevive_ao_json_da_fila():
    from app.models.schemas import QuizCreateRequest, QuizGroupSetup

    pedido = QuizCreateRequest(
        material_ids=["m1"], lesson_ids=["l1"], titulo="Quiz rapido: GRUPO 1",
        group_setup=QuizGroupSetup(discipline_id="d1", class_ids=["c-3002", "c-3030"],
                                   exclude_group_ids=["g1"]),
    )

    de_volta = QuizCreateRequest.model_validate(pedido.model_dump(mode="json"))

    assert de_volta.group_setup.exclude_group_ids == ["g1"]
    assert de_volta.group_setup.class_ids == ["c-3002", "c-3030"]
    assert de_volta.titulo == "Quiz rapido: GRUPO 1"


def test_pedido_antigo_sem_group_setup_continua_valido():
    from app.models.schemas import QuizCreateRequest

    pedido = QuizCreateRequest.model_validate({"material_ids": ["m1"]})

    assert pedido.group_setup is None and pedido.titulo is None


def test_valida_o_group_setup_ainda_no_pedido(api):
    from fastapi import HTTPException

    from app.models.schemas import QuizGroupSetup
    from app.routers import education

    async def validar(setup):
        async with api.sessions() as db:
            await education._validate_group_setup(setup, "t1", db)

    asyncio.run(validar(QuizGroupSetup(discipline_id="d1", exclude_group_ids=["g1"])))

    with pytest.raises(HTTPException) as unico:
        asyncio.run(validar(QuizGroupSetup(
            discipline_id="d1", class_ids=["c-qui"], exclude_group_ids=["g3"])))
    assert unico.value.status_code == 422
    with pytest.raises(HTTPException) as inexistente:
        asyncio.run(validar(QuizGroupSetup(discipline_id="d1", exclude_group_ids=["xx"])))
    assert inexistente.value.status_code == 404
    with pytest.raises(HTTPException) as alheia:
        asyncio.run(validar(QuizGroupSetup(discipline_id="nao-existe")))
    assert alheia.value.status_code == 404


def test_quiz_gerado_sai_em_grupo_sem_o_grupo_que_apresentou(api):
    from app.models.schemas import QuizGroupSetup
    from app.routers import quiz_group as router

    async def aplicar():
        async with api.sessions() as db:
            return await router.apply_group_setup(
                db, "quiz1", "t1",
                QuizGroupSetup(discipline_id="d1", class_ids=["c-3002", "c-3030"],
                               exclude_group_ids=["g1"], mode="media"))

    config = asyncio.run(aplicar())

    assert config.mode == "media" and config.semester == "2026.2"
    assert quiz_groups.config_class_ids(config) == ["c-3002", "c-3030"]
    assert quiz_groups.config_excluded_ids(config) == ["g1"]
    painel = api.get("/education/quiz/quiz1/group").json()
    assert nomes_dos_grupos(painel) == ["GRUPO 2"]


def test_titulo_do_quiz_rapido_vem_do_pedido(api):
    from app.models.schemas import QuizCreateRequest
    from app.routers import education

    async def montar(titulo):
        async with api.sessions() as db:
            if not await db.get(MaterialModel, "mat1"):
                db.add(MaterialModel(id="mat1", tutor_id="t1", discipline_id="d1",
                                     discipline="BD", title="Slides do G1", filename="g1.pdf",
                                     source_type="pdf", content="texto do slide " * 40,
                                     group_id="g1"))
                await db.commit()
            return await education._quiz_generation_context(
                QuizCreateRequest(material_ids=["mat1"], titulo=titulo), "t1", db)

    com_titulo = asyncio.run(montar("Quiz rapido: GRUPO 1"))
    sem_titulo = asyncio.run(montar(None))

    assert com_titulo["titulo"] == "Quiz rapido: GRUPO 1"
    assert sem_titulo["titulo"].startswith("Quiz: ")
