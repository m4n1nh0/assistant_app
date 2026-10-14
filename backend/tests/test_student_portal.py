"""Portal do aluno: o que cada aluno vê com a matrícula.

O que isto protege: o aluno vê só o que é dele ou coletivo da turma dele (nunca de outra
turma nem de outro professor), o acesso só por matrícula não pode ser varrido, e o portal
reflete o dado vivo - resumo, quiz, ponto, material e atividade da mentoria.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    ClassGroupModel,
    DisciplineModel,
    LessonClassGroupModel,
    LessonModel,
    LessonPointModel,
    MaterialModel,
    MentorshipActivityModel,
    MentorshipDeliveryModel,
    MentorshipFormModel,
    MentorshipSignupModel,
    ProjectGroupClassModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    QuestionModel,
    QuizGroupConfigModel,
    QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
    QuizModel,
    StudentAnswerModel,
    StudentModel,
    StudentPortalModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import student_portal

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (
    DisciplineModel, ClassGroupModel, StudentModel, LessonModel, LessonClassGroupModel,
    LessonPointModel, MaterialModel, ProjectGroupModel, ProjectGroupMemberModel, ProjectGroupClassModel,
    QuizModel, QuestionModel, StudentAnswerModel, QuizGroupConfigModel, QuizGroupLinkModel,
    QuizGroupRepresentativeModel, MentorshipFormModel, MentorshipSignupModel, MentorshipActivityModel,
    MentorshipDeliveryModel, StudentPortalModel,
)
AGORA = datetime(2026, 10, 10, 12, 0)


def agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def api():
    student_portal._hits.clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/p.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d-bd", tutor_id="t1", code="ARA0040", name="BD"),
                DisciplineModel(id="d-ment", tutor_id="t1", code="MENTORIA", name="Mentoria IA"),
                DisciplineModel(id="d-outra", tutor_id="t1", code="X", name="Outra"),
                ClassGroupModel(id="c-bd", tutor_id="t1", code="3001", name="Presencial",
                                discipline_id="d-bd", discipline="BD", semester="2026.2"),
                ClassGroupModel(id="c-ment", tutor_id="t1", code="MENTORIA", name="Mentoria IA",
                                discipline_id="d-ment", discipline="Mentoria IA",
                                semester="2026.2"),
                ClassGroupModel(id="c-outra", tutor_id="t1", code="9", name="Outra",
                                discipline_id="d-outra", discipline="Outra", semester="2026.2"),
                # Ana: graduacao e mentoria (dois registros, mesma matricula). Bia: so graduacao.
                StudentModel(id="s-ana-bd", tutor_id="t1", name="Ana Souza", class_id="c-bd",
                             class_group="x", external_id="2024-0001", active=True),
                StudentModel(id="s-ana-m", tutor_id="t1", name="Ana Souza", class_id="c-ment",
                             class_group="x", external_id="20240001", active=True),
                StudentModel(id="s-bia", tutor_id="t1", name="Bia Lima", class_id="c-bd",
                             class_group="x", external_id="20240002", active=True),
                StudentModel(id="s-fora", tutor_id="t1", name="Fora", class_id="c-outra",
                             class_group="x", external_id="20240003", active=True),
                StudentModel(id="s-inativo", tutor_id="t1", name="Inativo", class_id="c-bd",
                             class_group="x", external_id="20240004", active=False),
                # Aulas
                LessonModel(id="l-bd", tutor_id="t1", discipline="BD", title="Normalização",
                            summary="## Resumo\n- Primeira forma normal\n- **Segunda** forma",
                            started_at=AGORA, status="closed"),
                LessonModel(id="l-sem", tutor_id="t1", discipline="BD", title="Sem resumo",
                            summary="", started_at=AGORA, status="closed"),
                LessonModel(id="l-ment", tutor_id="t1", discipline="Mentoria IA",
                            title="Encontro 1", summary="Falamos de prompts.",
                            started_at=AGORA + timedelta(days=1), status="closed"),
                LessonModel(id="l-outra", tutor_id="t1", discipline="Outra",
                            title="De outra turma", summary="Segredo da outra turma",
                            started_at=AGORA, status="closed"),
                LessonClassGroupModel(lesson_id="l-bd", class_group_id="c-bd"),
                LessonClassGroupModel(lesson_id="l-sem", class_group_id="c-bd"),
                LessonClassGroupModel(lesson_id="l-ment", class_group_id="c-ment"),
                LessonClassGroupModel(lesson_id="l-outra", class_group_id="c-outra"),
                # Pontos
                LessonPointModel(tutor_id="t1", lesson_id="l-bd", student_id="s-ana-bd",
                                 student_name="Ana", points=1.5, reason="Boa pergunta",
                                 discipline="BD", lesson_date=AGORA),
                LessonPointModel(tutor_id="t1", lesson_id="l-bd", student_id="s-ana-bd",
                                 student_name="Ana", points=1.0, reason="Exemplo",
                                 discipline="BD", lesson_date=AGORA),
                LessonPointModel(tutor_id="t1", lesson_id="l-bd", student_id="s-bia",
                                 student_name="Bia", points=5.0, reason="Da Bia",
                                 discipline="BD", lesson_date=AGORA),
                # Materiais
                MaterialModel(id="m-bd", tutor_id="t1", discipline_id="d-bd", discipline="BD",
                              title="Apostila BD", filename="bd.pdf", content="Texto da apostila"),
                MaterialModel(id="m-grupo", tutor_id="t1", discipline_id="d-bd", discipline="BD",
                              title="Slides do grupo", filename="g.pptx", content="x",
                              group_id="g1"),
                MaterialModel(id="m-outra", tutor_id="t1", discipline_id="d-outra",
                              discipline="Outra", title="Apostila alheia", filename="o.pdf",
                              content="nao pode"),
                MaterialModel(id="m-ment", tutor_id="t1", discipline_id="d-ment",
                              discipline="Mentoria IA", title="Guia de prompts",
                              filename="p.pdf", content="Conteudo do guia"),
                # Mentoria: Ana aceita; atividade com entrega e outra vencida sem entrega
                MentorshipFormModel(id="f1", tutor_id="t1", token="tok-m", title="Mentoria IA",
                                    class_id="c-ment", discipline_id="d-ment", fields=[]),
                MentorshipSignupModel(id="su-ana", form_id="f1", tutor_id="t1",
                                      enrollment="2024-0001", enrollment_key="20240001",
                                      name="Ana Souza", email="a@x.com", phone="11",
                                      status="accepted"),
                MentorshipActivityModel(id="a1", form_id="f1", tutor_id="t1", title="Ler cap. 1",
                                        due_at=agora() - timedelta(days=2)),
                MentorshipActivityModel(id="a2", form_id="f1", tutor_id="t1", title="Projeto",
                                        due_at=agora() - timedelta(days=1), position=1),
                MentorshipActivityModel(id="a3", form_id="f1", tutor_id="t1", title="Futura",
                                        due_at=agora() + timedelta(days=5), position=2),
                MentorshipDeliveryModel(activity_id="a1", form_id="f1", signup_id="su-ana",
                                        tutor_id="t1", text="feito", late=False),
                # Portal
                StudentPortalModel(id="p1", tutor_id="t1", token="tok-portal", active=True),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(student_portal.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    client = TestClient(app)
    client.sessions = sessions
    return client


def consulta(api, matricula, token="tok-portal"):
    return api.post(f"/education/portal/{token}/lookup", json={"enrollment": matricula})


def test_aluno_ve_resumos_so_das_turmas_dele_e_so_os_que_tem_resumo(api):
    dados = consulta(api, "2024-0002").json()  # Bia: so graduacao

    titulos = [a["title"] for a in dados["lessons"]]
    assert titulos == ["Normalização"]
    assert "Primeira forma normal" in dados["lessons"][0]["summary"]
    assert "Segredo da outra turma" not in str(dados)
    assert [c["label"] for c in dados["classes"]] == ["3001 Presencial"]
    assert dados["mentorships"] == []


def test_aluno_de_graduacao_e_mentoria_ve_as_duas_e_a_mentoria_vem_marcada(api):
    dados = consulta(api, "20240001").json()

    por_titulo = {a["title"]: a for a in dados["lessons"]}
    assert set(por_titulo) == {"Normalização", "Encontro 1"}
    assert por_titulo["Encontro 1"]["mentorship"] is True
    assert por_titulo["Normalização"]["mentorship"] is False
    # Mais recente primeiro
    assert [a["title"] for a in dados["lessons"]] == ["Encontro 1", "Normalização"]


def test_matricula_com_pontuacao_diferente_e_a_mesma(api):
    assert consulta(api, " 2024 0001 ").status_code == 200
    assert consulta(api, "2024-0001").json()["student"]["name"] == "Ana Souza"


def test_pontos_extras_sao_so_do_proprio_aluno_com_o_total(api):
    ana = consulta(api, "20240001").json()["points"]
    bia = consulta(api, "20240002").json()["points"]

    assert ana["total"] == 2.5 and [i["reason"] for i in ana["items"]] == ["Boa pergunta", "Exemplo"]
    assert bia["total"] == 5.0 and "Da Bia" in str(bia)
    assert "Da Bia" not in str(ana)


def test_materiais_so_das_disciplinas_do_aluno_e_sem_os_dos_grupos(api):
    bia = consulta(api, "20240002").json()["materials"]
    ana = consulta(api, "20240001").json()["materials"]

    assert [m["title"] for m in bia] == ["Apostila BD"]
    assert {m["title"] for m in ana} == {"Apostila BD", "Guia de prompts"}
    assert "Apostila alheia" not in str(ana) and "Slides do grupo" not in str(ana)


def test_le_o_texto_do_material_so_se_for_da_disciplina_dele(api):
    url = "/education/portal/tok-portal/material"

    ok = api.post(url, json={"enrollment": "20240002", "material_id": "m-bd"})
    outra = api.post(url, json={"enrollment": "20240002", "material_id": "m-outra"})
    mentoria = api.post(url, json={"enrollment": "20240002", "material_id": "m-ment"})
    grupo = api.post(url, json={"enrollment": "20240002", "material_id": "m-grupo"})

    assert ok.json()["content"] == "Texto da apostila"
    assert outra.status_code == mentoria.status_code == grupo.status_code == 404


def test_mentoria_mostra_atividades_com_a_situacao_de_cada_uma(api):
    dados = consulta(api, "20240001").json()["mentorships"]

    assert len(dados) == 1 and dados[0]["title"] == "Mentoria IA"
    estados = {a["title"]: a["status"] for a in dados[0]["activities"]}
    assert estados == {"Ler cap. 1": "delivered", "Projeto": "overdue", "Futura": "pending"}
    assert dados[0]["deliver_path"] == "/education/mentorship-deliver/tok-m"


def test_mentoria_so_aparece_para_quem_foi_aceito(api):
    async def recusa():
        async with api.sessions() as db:
            item = await db.get(MentorshipSignupModel, "su-ana")
            item.status = "removed"
            await db.commit()

    asyncio.run(recusa())

    assert consulta(api, "20240001").json()["mentorships"] == []


def test_matricula_desconhecida_ou_inativa_ou_de_outro_professor_nao_entra(api):
    for matricula in ("99999999", "20240004", "", "   "):
        resposta = consulta(api, matricula)
        assert resposta.status_code == 404, matricula
        assert resposta.json()["code"] == "unknown"


def test_portal_fechado_ou_link_errado_nao_responde(api):
    api.patch("/education/portal-link", json={"active": False})

    assert consulta(api, "20240001").status_code == 404
    assert "fechado" in api.get("/education/portal/tok-portal").text
    assert "não existe" in api.get("/education/portal/errado").text
    assert consulta(api, "20240001", token="errado").status_code == 404


def test_professor_pega_o_link_e_ele_e_sempre_o_mesmo(api):
    primeiro = api.get("/education/portal-link").json()
    segundo = api.get("/education/portal-link").json()

    assert primeiro == segundo == {"path": "/education/portal/tok-portal", "active": True}


def test_cria_o_portal_na_primeira_vez(api):
    async def apaga():
        async with api.sessions() as db:
            await db.delete(await db.get(StudentPortalModel, "p1"))
            await db.commit()

    asyncio.run(apaga())

    criado = api.get("/education/portal-link").json()

    assert criado["path"].startswith("/education/portal/") and criado["active"] is True
    assert api.get("/education/portal-link").json() == criado


def test_varredura_de_matriculas_e_barrada_por_ip(api):
    for _ in range(student_portal.RATE_LIMIT):
        assert consulta(api, "00000000").status_code == 404

    barrado = consulta(api, "20240001")

    assert barrado.status_code == 429 and barrado.json()["code"] == "rate"
    assert "Retry-After" in barrado.headers


def test_limite_por_ip_libera_depois_da_janela():
    student_portal._hits.clear()
    for i in range(student_portal.RATE_LIMIT):
        assert student_portal._rate_limited("1.2.3.4", now=100.0 + i * 0.01) is False
    assert student_portal._rate_limited("1.2.3.4", now=101.0) is True
    assert student_portal._rate_limited("1.2.3.4", now=100.0 + student_portal.RATE_WINDOW_SECONDS + 5) is False
    assert student_portal._rate_limited("9.9.9.9", now=101.0) is False  # outro IP nao e afetado


def test_pagina_publica_tem_a_marca_e_nao_mostra_dado_antes_da_matricula(api):
    html = api.get("/education/portal/tok-portal").text

    assert "Portal do aluno" in html and "iq-bar" in html
    assert "Normalização" not in html and "Ana Souza" not in html


# --- quiz em grupo -----------------------------------------------------------------------


def seed_quiz(api, *, finished=True):
    """Dois grupos: Ana+Bia (g1) e outro (g2); Ana acerta 2, Bia acerta 1; g2 acerta 1."""
    OPCOES = '[{"label": "A", "texto": "Certa", "correta": true}]'

    async def run():
        async with api.sessions() as db:
            db.add_all([
                ProjectGroupModel(id="g1", tutor_id="t1", discipline_id="d-bd",
                                  semester="2026.2", name="Grupo 1"),
                ProjectGroupModel(id="g2", tutor_id="t1", discipline_id="d-bd",
                                  semester="2026.2", name="Grupo 2"),
                ProjectGroupMemberModel(id="m-ana", group_id="g1", student_id="s-ana-bd",
                                        name="Ana Souza", position=0),
                ProjectGroupMemberModel(id="m-bia", group_id="g1", student_id="s-bia",
                                        name="Bia Lima", position=1),
                ProjectGroupMemberModel(id="m-x", group_id="g2", student_id="s-fora",
                                        name="Fora", position=0),
                QuizModel(id="qz", tutor_id="t1", lesson_id="l-bd", titulo="Quiz de BD",
                          status="closed" if finished else "open", created_at=AGORA),
                QuestionModel(id="q1", quiz_id="qz", tipo="multipla_escolha", enunciado="1?",
                              opcoes=OPCOES, resposta_correta="A"),
                QuestionModel(id="q2", quiz_id="qz", tipo="multipla_escolha", enunciado="2?",
                              opcoes=OPCOES, resposta_correta="A"),
                QuizGroupConfigModel(quiz_id="qz", tutor_id="t1", mode="media",
                                     discipline_id="d-bd", class_ids="c-bd",
                                     semester="2026.2", seed="s"),
                QuizGroupLinkModel(quiz_id="qz", attempt_id="att-ana", group_id="g1",
                                   group_name="Grupo 1", member_id="m-ana",
                                   member_name="Ana Souza"),
                QuizGroupLinkModel(quiz_id="qz", attempt_id="att-bia", group_id="g1",
                                   group_name="Grupo 1", member_id="m-bia",
                                   member_name="Bia Lima"),
                QuizGroupLinkModel(quiz_id="qz", attempt_id="att-x", group_id="g2",
                                   group_name="Grupo 2", member_id="m-x", member_name="Fora"),
                StudentAnswerModel(question_id="q1", student_id="att-ana", correta=True,
                                   pontuacao=100),
                StudentAnswerModel(question_id="q2", student_id="att-ana", correta=True,
                                   pontuacao=100),
                StudentAnswerModel(question_id="q1", student_id="att-bia", correta=True,
                                   pontuacao=100),
                StudentAnswerModel(question_id="q1", student_id="att-x", correta=True,
                                   pontuacao=50),
            ])
            await db.commit()

    asyncio.run(run())


def test_resultado_do_quiz_em_grupo_traz_o_grupo_e_a_parte_do_aluno(api):
    seed_quiz(api)

    quizzes = consulta(api, "2024-0001").json()["quizzes"]

    assert len(quizzes) == 1
    q = quizzes[0]
    assert q["title"] == "Quiz de BD" and q["group_name"] == "Grupo 1" and q["finished"] is True
    assert (q["my_score"], q["my_correct"], q["my_answers"]) == (200, 2, 2)
    assert q["position"] == 1 and q["groups_total"] == 2
    assert q["group_score"] == 150  # media de Ana (200) e Bia (100)


def test_quiz_nao_mostra_o_resultado_de_colegas_nem_de_outro_grupo(api):
    seed_quiz(api)

    bia = consulta(api, "20240002").json()["quizzes"][0]

    assert bia["my_score"] == 100 and bia["my_correct"] == 1
    assert "Ana" not in str(bia) and "Fora" not in str(bia)


def test_quiz_em_andamento_vem_marcado_e_quem_nao_respondeu_nao_ve(api):
    seed_quiz(api, finished=False)

    assert consulta(api, "20240002").json()["quizzes"][0]["finished"] is False
    # Aluno de outra turma/disciplina nao tem o quiz
    assert consulta(api, "20240003").json()["quizzes"] == []
