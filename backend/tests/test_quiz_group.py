"""Quiz em grupo de ponta a ponta: o professor liga o modo e o aluno entra pela matricula."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    DisciplineModel,
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
from app.routers import education, quiz_group, quiz_play

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    DisciplineModel, ProjectGroupModel, ProjectGroupMemberModel, StudentModel,
    QuizModel, QuestionModel, QuizParticipantModel, StudentAnswerModel,
    QuestionTranslationModel, QuizGroupConfigModel, QuizGroupLinkModel,
    QuizGroupRepresentativeModel, QuizJobModel, QuizSourceModel,
)
OPCOES = (
    '[{"label": "A", "texto": "Certa", "correta": true},'
    ' {"label": "B", "texto": "Errada", "correta": false}]'
)

# matricula digitada -> nome no cadastro do grupo
ANA, BIA, CAIO, DAVI, EVA = "2024-0001", "20240002", "20240003", "20240004", "20240005"


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/g.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def aluno(id_, nome, matricula):
        return StudentModel(id=id_, tutor_id="t1", name=nome, external_id=matricula)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0040", name="BANCO DE DADOS"),
                DisciplineModel(id="d-vazia", tutor_id="t1", code="X", name="Sem grupos"),
                DisciplineModel(id="d-alheia", tutor_id="t2", code="Y", name="De outro"),
                aluno("s-ana", "Ana Souza", "20240001"),
                aluno("s-bia", "Bia Lima", "20240002"),
                aluno("s-caio", "Caio Reis", None),  # sem matricula: nao consegue entrar
                aluno("s-davi", "Davi Alves", "20240004"),
                aluno("s-eva", "Eva Costa", "20240005"),
                ProjectGroupModel(id="g1", tutor_id="t1", discipline_id="d1", semester="2026.2", name="Grupo 1"),
                ProjectGroupModel(id="g2", tutor_id="t1", discipline_id="d1", semester="2026.2", name="Grupo 2"),
                ProjectGroupMemberModel(id="m-ana", group_id="g1", student_id="s-ana", name="Ana Souza", position=0),
                ProjectGroupMemberModel(id="m-bia", group_id="g1", student_id="s-bia", name="Bia Lima", position=1),
                ProjectGroupMemberModel(id="m-caio", group_id="g1", student_id="s-caio", name="Caio Reis", position=2),
                ProjectGroupMemberModel(id="m-davi", group_id="g2", student_id="s-davi", name="Davi Alves", position=0),
                ProjectGroupMemberModel(id="m-eva", group_id="g2", student_id="s-eva", name="Eva Costa", position=1),
                QuizModel(
                    id="quiz1", tutor_id="t1", lesson_id="aula", titulo="Quiz BD", status="open",
                    live_phase="question", current_question_id="q1",
                    question_started_at=datetime.now(timezone.utc), time_limit_seconds=0,
                ),
                QuizModel(id="alheio", tutor_id="t2", lesson_id="aula", titulo="De outro", status="open"),
                QuestionModel(
                    id="q1", quiz_id="quiz1", tipo="multipla_escolha", enunciado="Primeira?",
                    opcoes=OPCOES, resposta_correta="A",
                ),
                QuestionModel(
                    id="q2", quiz_id="quiz1", tipo="multipla_escolha", enunciado="Segunda?",
                    opcoes=OPCOES, resposta_correta="A",
                ),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    for router in (quiz_group.router, quiz_play.router, education.router):
        app.include_router(router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        client.sessions = sessions
        client.app_ref = app
        yield client
    asyncio.run(engine.dispose())


def novo_aparelho(api) -> TestClient:
    """Outro celular: mesma app, cookies proprios."""
    return TestClient(api.app_ref)


def ligar(api, mode="media", discipline="d1"):
    return api.put(
        "/education/quiz/quiz1/group",
        json={"mode": mode, "discipline_id": discipline, "semester": "2026.2"},
    )


def entrar(aparelho, matricula):
    return aparelho.post(
        "/education/quiz/quiz1/play", data={"enrollment": matricula}, follow_redirects=False
    )


def responder(aparelho, resposta="A", pergunta="q1"):
    return aparelho.post(
        "/education/quiz/quiz1/play",
        data={"answer": resposta, "question_id": pergunta},
        follow_redirects=False,
    )


def consultar(api, consulta):
    async def executar():
        async with api.sessions() as db:
            return await consulta(db)

    return asyncio.run(executar())


def respostas(api):
    return consultar(api, lambda db: _todas(db))


async def _todas(db):
    return list((await db.execute(select(StudentAnswerModel))).scalars())


def linha(painel, grupo):
    return next(item for item in painel["ranking"] if item["student_id"] == grupo)


# --- professor ----------------------------------------------------------------------


@pytest.mark.integration
def test_quiz_individual_por_padrao(api):
    assert api.get("/education/quiz/quiz1/group").json() == {"enabled": False}


@pytest.mark.integration
def test_liga_o_modo_e_mostra_grupos_com_quem_pode_entrar(api):
    encerrar_pergunta(api)
    painel = ligar(api, "media").json()

    assert painel["enabled"] is True and painel["mode"] == "media"
    assert painel["discipline"] == "ARA0040 - BANCO DE DADOS"
    nomes = {g["name"]: g for g in painel["groups"]}
    assert set(nomes) == {"Grupo 1", "Grupo 2"}
    elegivel = {m["name"]: m["eligible"] for m in nomes["Grupo 1"]["members"]}
    # Caio nao tem matricula cadastrada: nao tem como se identificar no quiz.
    assert elegivel == {"Ana Souza": True, "Bia Lima": True, "Caio Reis": False}
    assert painel["seed"] and painel["algorithm"] == "sha256-v1"


@pytest.mark.integration
def test_recusa_disciplina_sem_grupos_ou_de_outro_professor_ou_quiz_alheio(api):
    encerrar_pergunta(api)
    corpo = {"mode": "media", "semester": ""}
    assert api.put("/education/quiz/quiz1/group", json={**corpo, "discipline_id": "d-vazia"}).status_code == 422
    assert api.put("/education/quiz/quiz1/group", json={**corpo, "discipline_id": "d-alheia"}).status_code == 404
    assert api.put("/education/quiz/quiz1/group", json={**corpo, "discipline_id": "nao-existe"}).status_code == 404
    assert api.put("/education/quiz/alheio/group", json={**corpo, "discipline_id": "d1"}).status_code == 404
    assert api.get("/education/quiz/alheio/group").status_code == 404
    assert api.put("/education/quiz/quiz1/group", json={"mode": "outro", "discipline_id": "d1"}).status_code == 422


@pytest.mark.integration
def test_nao_liga_quiz_encerrado_nem_com_pergunta_aberta(api):
    # quiz1 esta com uma pergunta aberta para a turma.
    resposta = ligar(api)
    assert resposta.status_code == 409 and "pergunta aberta" in resposta.json()["detail"]


def encerrar_pergunta(api):
    async def executar(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.live_phase = "lobby"
        await db.commit()

    consultar(api, executar)


@pytest.mark.integration
def test_com_a_pergunta_encerrada_liga_e_desliga(api):
    encerrar_pergunta(api)
    assert ligar(api).status_code == 200
    assert api.delete("/education/quiz/quiz1/group").json() == {"enabled": False}
    assert api.get("/education/quiz/quiz1/group").json() == {"enabled": False}


# --- aluno: entrada pela matricula ---------------------------------------------------


def ligar_e_abrir(api, mode="media"):
    encerrar_pergunta(api)
    assert ligar(api, mode).status_code == 200

    async def abrir(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.live_phase = "question"
        await db.commit()

    consultar(api, abrir)


@pytest.mark.integration
def test_quiz_em_grupo_pede_matricula_e_nao_nome(api):
    ligar_e_abrir(api)
    pagina = novo_aparelho(api).get("/education/quiz/quiz1/play").text

    assert 'name="enrollment"' in pagina and 'name="student_name"' not in pagina
    assert "Quiz em grupo" in pagina


@pytest.mark.integration
@pytest.mark.parametrize(
    "matricula, trecho",
    [
        ("   ", "Digite a sua matrícula"),
        ("99999999", "Não encontrei essa matrícula"),
        (CAIO, "Não encontrei essa matrícula"),  # existe, mas sem matricula cadastrada no aluno
    ],
)
def test_matricula_invalida_mostra_o_erro_e_nao_entra(api, matricula, trecho):
    ligar_e_abrir(api)
    aparelho = novo_aparelho(api)

    pagina = entrar(aparelho, matricula)

    assert pagina.status_code == 200 and trecho in pagina.text
    assert 'name="enrollment"' in pagina.text
    assert consultar(api, lambda db: _contar(db, QuizGroupLinkModel)) == 0


async def _contar(db, model):
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


@pytest.mark.integration
def test_matricula_liga_o_aluno_ao_grupo_e_usa_o_nome_do_cadastro(api):
    ligar_e_abrir(api)
    ana = novo_aparelho(api)

    assert entrar(ana, ANA).status_code == 303  # "2024-001" casa com 20240001

    link = consultar(api, lambda db: db.scalar(select(QuizGroupLinkModel)))
    assert (link.group_id, link.group_name, link.member_name) == ("g1", "Grupo 1", "Ana Souza")
    pagina = ana.get("/education/quiz/quiz1/play").text
    assert "Primeira?" in pagina and "Ana Souza" in pagina


@pytest.mark.integration
def test_cookie_com_nome_nao_burla_a_matricula(api):
    ligar_e_abrir(api)
    intruso = novo_aparelho(api)
    intruso.cookies.set("intarq_quiz_student_quiz1", "Qualquer Um")

    pagina = intruso.get("/education/quiz/quiz1/play").text

    assert 'name="enrollment"' in pagina and "Primeira?" not in pagina


# --- modo media -----------------------------------------------------------------------


@pytest.mark.integration
def test_media_do_grupo_so_conta_quem_entrou(api):
    ligar_e_abrir(api, "media")
    ana, bia, davi = novo_aparelho(api), novo_aparelho(api), novo_aparelho(api)
    entrar(ana, ANA)
    entrar(bia, BIA)
    entrar(davi, DAVI)

    assert responder(ana, "A").status_code == 303
    assert responder(bia, "B").status_code == 303  # errou: 0 ponto
    assert responder(davi, "A").status_code == 303

    pontos = {a.student_name: a.pontuacao for a in respostas(api)}
    assert pontos["Bia Lima"] == 0 and pontos["Ana Souza"] > 0

    painel = api.get("/education/quiz/quiz1/group").json()
    assert linha(painel, "g1")["score"] == round(pontos["Ana Souza"] / 2)
    assert linha(painel, "g2")["score"] == pontos["Davi Alves"]
    grupo1 = linha(painel, "g1")
    assert grupo1["members"] == 2 and grupo1["members_total"] == 3
    assert [item["position"] for item in painel["ranking"]] == [1, 2]


@pytest.mark.integration
def test_ranking_do_aluno_mostra_grupos_e_destaca_o_dele(api):
    ligar_e_abrir(api, "media")
    ana, davi = novo_aparelho(api), novo_aparelho(api)
    entrar(ana, ANA)
    entrar(davi, DAVI)
    responder(ana, "A")
    responder(davi, "A")

    async def mostrar_ranking(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.live_phase = "results"
        await db.commit()

    consultar(api, mostrar_ranking)
    pagina = ana.get("/education/quiz/quiz1/play").text

    assert "Grupo 1" in pagina and "Grupo 2" in pagina
    assert 'class="me"' in pagina


# --- modo representante ---------------------------------------------------------------


@pytest.mark.integration
def test_sorteio_de_representantes_so_escolhe_quem_tem_matricula(api):
    encerrar_pergunta(api)
    ligar(api, "representante")

    painel = api.post("/education/quiz/quiz1/group/representatives/draw", json={}).json()

    assert sorted(painel["draw_result"]["drawn"]) == ["g1", "g2"]
    reps = {g["name"]: g["representative"] for g in painel["groups"]}
    assert reps["Grupo 1"]["name"] in {"Ana Souza", "Bia Lima"}  # nunca o Caio
    assert reps["Grupo 2"]["name"] in {"Davi Alves", "Eva Costa"}
    assert painel["without_representative"] == []

    repetido = api.post("/education/quiz/quiz1/group/representatives/draw", json={}).json()
    assert repetido["draw_result"]["drawn"] == []  # ja tem: nao refaz sem pedir
    refeito = api.post(
        "/education/quiz/quiz1/group/representatives/draw", json={"redraw": True}
    ).json()
    assert sorted(refeito["draw_result"]["drawn"]) == ["g1", "g2"]


@pytest.mark.integration
def test_redefinir_e_escolher_representante_manualmente(api):
    encerrar_pergunta(api)
    ligar(api, "representante")
    base = "/education/quiz/quiz1/group/representatives"

    manual = api.put(f"{base}/g1", json={"member_id": "m-bia"}).json()
    rep = next(g for g in manual["groups"] if g["id"] == "g1")["representative"]
    assert (rep["name"], rep["origin"]) == ("Bia Lima", "manual")

    assert api.put(f"{base}/g1", json={"member_id": "m-caio"}).status_code == 422  # sem matricula
    assert api.put(f"{base}/g1", json={"member_id": "m-davi"}).status_code == 422  # de outro grupo
    assert api.put(f"{base}/nao-existe", json={"member_id": "m-bia"}).status_code == 404

    sorteado = api.post(f"{base}/g1/redraw").json()
    rep = next(g for g in sorteado["groups"] if g["id"] == "g1")["representative"]
    assert rep["origin"] == "sorteio" and rep["round"] == 1  # troca a escolha manual


@pytest.mark.integration
def test_so_o_representante_responde_e_o_grupo_vale_o_que_ele_fez(api):
    encerrar_pergunta(api)
    ligar(api, "representante")
    api.put("/education/quiz/quiz1/group/representatives/g1", json={"member_id": "m-bia"})
    api.put("/education/quiz/quiz1/group/representatives/g2", json={"member_id": "m-davi"})

    async def abrir(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.live_phase = "question"
        await db.commit()

    consultar(api, abrir)

    ana, bia = novo_aparelho(api), novo_aparelho(api)
    entrar(ana, ANA)
    entrar(bia, BIA)

    # Ana nao e a representante: ve o aviso, nao a pergunta, e a resposta dela nao conta.
    pagina_ana = ana.get("/education/quiz/quiz1/play").text
    assert "Quem responde é o representante" in pagina_ana and "Bia Lima" in pagina_ana
    assert "Primeira?" not in pagina_ana
    responder(ana, "A")
    assert respostas(api) == []

    assert "Primeira?" in bia.get("/education/quiz/quiz1/play").text
    responder(bia, "A")
    gravadas = respostas(api)
    assert [a.student_name for a in gravadas] == ["Bia Lima"]

    painel = api.get("/education/quiz/quiz1/group").json()
    assert linha(painel, "g1")["score"] == gravadas[0].pontuacao
    assert linha(painel, "g1")["representative"] == "Bia Lima"


@pytest.mark.integration
def test_grupo_sem_representante_avisa_o_integrante(api):
    encerrar_pergunta(api)
    ligar(api, "representante")

    async def abrir(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.live_phase = "question"
        await db.commit()

    consultar(api, abrir)
    ana = novo_aparelho(api)
    entrar(ana, ANA)

    pagina = ana.get("/education/quiz/quiz1/play").text
    assert "ainda não escolheu o representante do Grupo 1" in pagina


# --- travas ---------------------------------------------------------------------------


@pytest.mark.integration
def test_depois_que_a_turma_respondeu_nao_muda_o_modo_nem_volta_a_individual(api):
    ligar_e_abrir(api, "media")
    ana = novo_aparelho(api)
    entrar(ana, ANA)
    responder(ana, "A")
    encerrar_pergunta(api)

    assert ligar(api, "representante").status_code == 409
    assert api.delete("/education/quiz/quiz1/group").status_code == 409
    # Mesma configuracao e aceita: nao ha o que perder.
    assert ligar(api, "media").status_code == 200


@pytest.mark.integration
def test_quiz_encerrado_nao_aceita_mudanca_de_grupo(api):
    async def encerrar(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.status = "closed"
        await db.commit()

    consultar(api, encerrar)
    resposta = ligar(api)
    assert resposta.status_code == 409 and "encerrado" in resposta.json()["detail"]


@pytest.mark.integration
def test_apagar_o_quiz_leva_a_configuracao_de_grupo(api):
    ligar_e_abrir(api, "representante")
    api.put("/education/quiz/quiz1/group/representatives/g1", json={"member_id": "m-bia"})
    ana = novo_aparelho(api)
    entrar(ana, ANA)
    encerrar_pergunta(api)

    assert api.delete("/education/quiz/quiz1", params={"force": "true"}).status_code == 200

    for model in (QuizGroupConfigModel, QuizGroupLinkModel, QuizGroupRepresentativeModel):
        assert consultar(api, lambda db, m=model: _contar(db, m)) == 0


# --- penalidade por ausente -------------------------------------------------------------


def configurar(api, mode="media", absence="none", percent=0, discipline="d1"):
    return api.put(
        "/education/quiz/quiz1/group",
        json={
            "mode": mode, "discipline_id": discipline, "semester": "2026.2",
            "absence_mode": absence, "absence_percent": percent,
        },
    )


@pytest.mark.integration
def test_configuracao_devolve_a_penalidade_e_os_ausentes_por_grupo(api):
    encerrar_pergunta(api)

    painel = configurar(api, "media", "percent", 10).json()

    assert painel["absence_mode"] == "percent" and painel["absence_percent"] == 10
    grupos = {g["name"]: g for g in painel["groups"]}
    # Ninguem entrou: so quem podia entrar e nao entrou e ausente (o Caio nao podia).
    assert grupos["Grupo 1"]["absent"] == ["Ana Souza", "Bia Lima"]
    assert grupos["Grupo 1"]["penalty_percent"] == 20
    assert grupos["Grupo 2"]["absent"] == ["Davi Alves", "Eva Costa"]


@pytest.mark.integration
def test_validacoes_da_penalidade(api):
    encerrar_pergunta(api)

    zero_no_representante = configurar(api, "representante", "zero")
    assert zero_no_representante.status_code == 422
    assert "só vale na média" in zero_no_representante.json()["detail"]
    assert configurar(api, "media", "percent", 0).status_code == 422
    assert configurar(api, "media", "percent", 101).status_code == 422
    assert configurar(api, "media", "outra").status_code == 422
    # Percentual solto com o modo desligado e ignorado, nao e erro.
    painel = configurar(api, "media", "none", 30).json()
    assert painel["absence_mode"] == "none" and painel["absence_percent"] == 0


@pytest.mark.integration
def test_ranking_com_desconto_por_ausente(api):
    encerrar_pergunta(api)
    configurar(api, "media", "percent", 10)
    consultar(api, _abrir_pergunta)
    ana, davi = novo_aparelho(api), novo_aparelho(api)
    entrar(ana, ANA)
    entrar(davi, DAVI)
    responder(ana, "A")
    responder(davi, "A")

    pontos = {a.student_name: a.pontuacao for a in respostas(api)}
    painel = api.get("/education/quiz/quiz1/group").json()
    g1, g2 = linha(painel, "g1"), linha(painel, "g2")

    # G1: Bia podia entrar e faltou; o Caio nao podia e nao conta.
    assert g1["absent_names"] == ["Bia Lima"] and g1["penalty_percent"] == 10
    assert g1["score_before_penalty"] == pontos["Ana Souza"]
    assert g1["score"] == round(pontos["Ana Souza"] * 0.9)
    assert g2["absent_names"] == ["Eva Costa"]
    assert g2["score"] == round(pontos["Davi Alves"] * 0.9)


async def _abrir_pergunta(db):
    quiz = await db.get(QuizModel, "quiz1")
    quiz.live_phase = "question"
    await db.commit()


@pytest.mark.integration
def test_ausente_conta_zero_divide_pela_turma_que_podia_entrar(api):
    encerrar_pergunta(api)
    configurar(api, "media", "zero")
    consultar(api, _abrir_pergunta)
    ana = novo_aparelho(api)
    entrar(ana, ANA)
    responder(ana, "A")

    pontos = {a.student_name: a.pontuacao for a in respostas(api)}
    g1 = linha(api.get("/education/quiz/quiz1/group").json(), "g1")

    # Ana respondeu, Bia podia e nao veio: media sobre os dois.
    assert g1["score"] == round(pontos["Ana Souza"] / 2)
    assert g1["absent_names"] == ["Bia Lima"]


@pytest.mark.integration
def test_penalidade_pode_mudar_depois_que_a_turma_respondeu_e_com_o_quiz_encerrado(api):
    encerrar_pergunta(api)
    configurar(api, "media", "none")
    consultar(api, _abrir_pergunta)
    ana = novo_aparelho(api)
    entrar(ana, ANA)
    responder(ana, "A")
    encerrar_pergunta(api)

    # So a penalidade muda: a configuracao estrutural e a mesma.
    assert configurar(api, "media", "percent", 20).status_code == 200
    # Mudar o modo continua travado depois das respostas.
    assert configurar(api, "representante", "none").status_code == 409

    async def encerrar(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.status = "closed"
        await db.commit()

    consultar(api, encerrar)
    corrigido = configurar(api, "media", "zero")
    assert corrigido.status_code == 200 and corrigido.json()["absence_mode"] == "zero"
    # Estrutura diferente num quiz encerrado segue recusada.
    assert configurar(api, "representante", "none").status_code == 409


@pytest.mark.integration
def test_ranking_do_aluno_ja_traz_a_nota_com_o_desconto(api):
    encerrar_pergunta(api)
    configurar(api, "media", "percent", 50)
    consultar(api, _abrir_pergunta)
    ana = novo_aparelho(api)
    entrar(ana, ANA)
    responder(ana, "A")
    pontos = {a.student_name: a.pontuacao for a in respostas(api)}

    async def mostrar_ranking(db):
        quiz = await db.get(QuizModel, "quiz1")
        quiz.live_phase = "results"
        await db.commit()

    consultar(api, mostrar_ranking)
    pagina = ana.get("/education/quiz/quiz1/play").text

    assert f"{round(pontos['Ana Souza'] * 0.5)} pontos" in pagina
