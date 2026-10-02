"""Relatorio de desempenho do quiz, por aluno e por pergunta.

O que importa nas contas:

- so conta pergunta que a turma chegou a ver: quiz encerrado antes do fim nao pode
  derrubar o percentual de todo mundo com perguntas que ninguem viu;
- quem entrou e nao respondeu aparece, com zero: o ranking ao vivo so conhece quem
  respondeu;
- o aluno e a tentativa (o navegador), nao uma pessoa: dois navegadores com o mesmo
  nome sao duas linhas.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    LessonModel,
    QuestionModel,
    QuizModel,
    QuizParticipantModel,
    QuizSourceModel,
    StudentAnswerModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education
from app.services import quiz_report_service as report

BASE = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
USER = {"uid": "u1", "tutor_id": "t1"}
OPCOES = json.dumps([
    {"label": "A", "texto": "3FN", "correta": True},
    {"label": "B", "texto": "1FN", "correta": False},
    {"label": "C", "texto": "2FN", "correta": False},
])


def _quiz(**extra) -> QuizModel:
    return QuizModel(
        id="quiz", tutor_id="t1", lesson_id="l1", titulo="Modelagem",
        tipo_quiz="pratica", status="closed", live_phase="finished",
        total_questoes=3, created_at=BASE, **extra,
    )


def _questions(n=3):
    return [
        QuestionModel(
            id=f"p{i}", quiz_id="quiz", tipo="multipla_escolha", dificuldade="medio",
            enunciado=f"Pergunta {i}?", opcoes=OPCOES, resposta_correta="A",
            created_at=BASE + timedelta(seconds=i),
        )
        for i in range(1, n + 1)
    ]


def _who(attempt, name):
    return QuizParticipantModel(quiz_id="quiz", attempt_id=attempt, student_name=name)


def _answer(question, attempt, name, label, *, correct, points=0, ms=5000):
    return StudentAnswerModel(
        id=f"{question}-{attempt}", question_id=question, student_id=attempt,
        student_name=name, resposta=label, correta=correct, pontuacao=points,
        tempo_resposta=ms,
    )


def _class():
    """Ana (2 acertos), Bia (1 acerto, 1 erro), Caio (entrou e nao respondeu)."""
    participants = [_who("a", "Ana"), _who("b", "Bia"), _who("c", "Caio")]
    answers = [
        _answer("p1", "a", "Ana", "A", correct=True, points=900, ms=2000),
        _answer("p2", "a", "Ana", "A", correct=True, points=800, ms=4000),
        _answer("p1", "b", "Bia", "B", correct=False, ms=9000),
        _answer("p2", "b", "Bia", "A", correct=True, points=500, ms=6000),
    ]
    return participants, answers


def build(quiz=None, questions=None, participants=None, answers=None):
    default_participants, default_answers = _class()
    return report.build_report(
        quiz=quiz or _quiz(),
        questions=questions or _questions(),
        participants=default_participants if participants is None else participants,
        answers=default_answers if answers is None else answers,
        disciplines=["Banco de Dados"],
        sources=["Aula 3"],
    )


def aluno(rel, nome):
    return next(a for a in rel["alunos"] if a["nome"] == nome)


# --- por aluno ---------------------------------------------------------------


@pytest.mark.unit
def test_pergunta_que_ninguem_viu_nao_entra_na_conta():
    rel = build()

    # p3 nunca foi aplicada (sem resposta, e o quiz ja acabou).
    assert rel["quiz"]["perguntas_aplicadas"] == 2
    assert rel["quiz"]["total_questoes"] == 3
    assert [p["aplicada"] for p in rel["perguntas"]] == [True, True, False]
    # Ana acertou as 2 que a turma viu: 100%, nao 67%.
    assert aluno(rel, "Ana")["percentual"] == 100.0
    assert aluno(rel, "Bia")["percentual"] == 50.0


@pytest.mark.unit
def test_pergunta_aberta_agora_conta_mesmo_sem_resposta():
    quiz = _quiz()
    quiz.status, quiz.live_phase, quiz.current_question_id = "open", "question", "p3"

    rel = build(quiz=quiz)

    assert rel["quiz"]["perguntas_aplicadas"] == 3
    assert aluno(rel, "Ana")["sem_resposta"] == 1
    assert aluno(rel, "Ana")["percentual"] == 66.7


@pytest.mark.unit
def test_quem_entrou_e_nao_respondeu_aparece_com_zero():
    rel = build()

    caio = aluno(rel, "Caio")
    assert caio["pontos"] == 0
    assert caio["respondidas"] == 0
    assert caio["sem_resposta"] == 2
    assert caio["percentual"] == 0.0
    assert rel["resumo"]["participantes"] == 3
    assert rel["resumo"]["responderam"] == 2
    assert rel["resumo"]["sem_resposta_nenhuma"] == 1
    assert rel["atencao"]["alunos_sem_resposta"] == ["Caio"]


@pytest.mark.unit
def test_posicao_segue_pontos_depois_acertos_e_quem_respondeu_antes_de_quem_so_entrou():
    rel = build()

    assert [(a["nome"], a["posicao"]) for a in rel["alunos"]] == [
        ("Ana", 1), ("Bia", 2), ("Caio", 3),
    ]
    assert aluno(rel, "Ana")["pontos"] == 1700
    assert aluno(rel, "Bia")["pontos"] == 500


@pytest.mark.unit
def test_empate_em_zero_poe_quem_respondeu_antes_de_quem_so_entrou():
    participants = [_who("a", "Zeca"), _who("b", "Ana")]
    answers = [_answer("p1", "a", "Zeca", "B", correct=False)]

    rel = build(participants=participants, answers=answers)

    # Os dois com 0 ponto e 0 acerto; Zeca respondeu e Ana so entrou.
    assert [a["nome"] for a in rel["alunos"]] == ["Zeca", "Ana"]


@pytest.mark.unit
def test_detalhe_por_pergunta_do_aluno():
    rel = build()

    bia = aluno(rel, "Bia")["por_pergunta"]
    assert [(p["indice"], p["status"], p["resposta"], p["pontos"]) for p in bia] == [
        (0, "errou", "B", 0),
        (1, "acertou", "A", 500),
    ]
    caio = aluno(rel, "Caio")["por_pergunta"]
    assert [p["status"] for p in caio] == ["sem_resposta", "sem_resposta"]
    assert aluno(rel, "Ana")["tempo_medio_ms"] == 3000


@pytest.mark.unit
def test_pergunta_pulada_e_contada_a_parte():
    answers = [
        _answer("p1", "a", "Ana", "", correct=None),
        _answer("p2", "a", "Ana", "A", correct=True, points=700),
    ]

    rel = build(participants=[_who("a", "Ana")], answers=answers)

    ana = aluno(rel, "Ana")
    assert (ana["acertos"], ana["erros"], ana["puladas"], ana["respondidas"]) == (1, 0, 1, 2)
    assert ana["por_pergunta"][0]["status"] == "pulou"


@pytest.mark.unit
def test_aluno_sem_cadastro_na_entrada_usa_o_nome_da_resposta():
    answers = [_answer("p1", "x", "Dani", "A", correct=True, points=600)]

    rel = build(participants=[], answers=answers)

    assert [a["nome"] for a in rel["alunos"]] == ["Dani"]


@pytest.mark.unit
def test_dois_navegadores_com_o_mesmo_nome_sao_duas_linhas():
    participants = [_who("a", "Ana"), _who("b", "Ana")]

    rel = build(participants=participants, answers=[])

    assert [a["nome"] for a in rel["alunos"]] == ["Ana", "Ana"]
    assert rel["resumo"]["participantes"] == 2


# --- por pergunta --------------------------------------------------------------


@pytest.mark.unit
def test_pergunta_mostra_acertos_percentual_e_quem_nao_respondeu():
    rel = build()

    p1 = rel["perguntas"][0]
    assert (p1["respostas"], p1["acertos"], p1["erros"]) == (2, 1, 1)
    assert p1["percentual"] == 50.0
    assert p1["sem_resposta"] == 1, "Caio entrou e nao respondeu a p1"
    assert p1["correta"] == "A"
    # p3 nao foi aplicada: ninguem "deixou de responder" o que nao viu.
    assert rel["perguntas"][2]["sem_resposta"] == 0


@pytest.mark.unit
def test_distribuicao_mostra_qual_alternativa_a_turma_escolheu():
    rel = build()

    p1 = rel["perguntas"][0]
    assert [(d["label"], d["quantidade"], d["correta"]) for d in p1["distribuicao"]] == [
        ("A", 1, True), ("B", 1, False), ("C", 0, False),
    ]
    assert p1["mais_escolhida_errada"]["label"] == "B"
    assert rel["perguntas"][1]["mais_escolhida_errada"] is None


@pytest.mark.unit
def test_resumo_da_turma():
    rel = build()

    resumo = rel["resumo"]
    assert (resumo["acertos"], resumo["erros"]) == (3, 1)
    assert resumo["taxa_acerto"] == 75.0
    assert resumo["respostas"] == 4
    assert resumo["pontos_medios"] == 733  # (1700 + 500 + 0) / 3
    assert resumo["tempo_medio_ms"] == 5250
    assert rel["quiz"]["disciplinas"] == ["Banco de Dados"]
    assert rel["quiz"]["fontes"] == ["Aula 3"]


# --- pontos de atencao ----------------------------------------------------------


@pytest.mark.unit
def test_pergunta_que_a_turma_errou_entra_em_atencao_com_a_alternativa_mais_escolhida():
    participants = [_who(k, k.upper()) for k in "abcd"]
    answers = [
        _answer("p1", k, k.upper(), "B", correct=False) for k in "abc"
    ] + [_answer("p1", "d", "D", "A", correct=True, points=600)]

    rel = build(participants=participants, answers=answers)

    fraca = rel["atencao"]["perguntas"]
    assert [(f["indice"], f["percentual"], f["respostas"]) for f in fraca] == [(0, 25.0, 4)]
    assert fraca[0]["mais_escolhida_errada"]["label"] == "B"


@pytest.mark.unit
def test_pergunta_com_poucas_respostas_nao_serve_de_sinal():
    participants = [_who("a", "Ana"), _who("b", "Bia")]
    answers = [
        _answer("p1", "a", "Ana", "B", correct=False),
        _answer("p1", "b", "Bia", "B", correct=False),
    ]

    rel = build(participants=participants, answers=answers)

    assert rel["atencao"]["perguntas"] == []


@pytest.mark.unit
def test_aluno_com_menos_da_metade_de_acerto_precisa_de_apoio_e_quem_nao_respondeu_nao():
    participants = [_who("a", "Ana"), _who("b", "Bia"), _who("c", "Caio")]
    answers = [
        _answer("p1", "a", "Ana", "A", correct=True, points=900),
        _answer("p2", "a", "Ana", "A", correct=True, points=900),
        _answer("p1", "b", "Bia", "B", correct=False),
        _answer("p2", "b", "Bia", "C", correct=False),
    ]

    rel = build(participants=participants, answers=answers)

    assert rel["atencao"]["alunos_com_dificuldade"] == ["Bia"]
    assert rel["atencao"]["alunos_sem_resposta"] == ["Caio"]


@pytest.mark.unit
def test_quiz_sem_ninguem_nao_divide_por_zero():
    quiz = _quiz()
    quiz.status, quiz.live_phase = "draft", "lobby"

    rel = build(quiz=quiz, participants=[], answers=[])

    assert rel["alunos"] == []
    assert rel["resumo"]["participantes"] == 0
    assert rel["resumo"]["taxa_acerto"] == 0.0
    assert rel["resumo"]["pontos_medios"] == 0
    assert rel["resumo"]["tempo_medio_ms"] is None
    assert rel["quiz"]["perguntas_aplicadas"] == 0


# --- endpoint --------------------------------------------------------------------


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/quiz.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, StudentAnswerModel,
                          QuizParticipantModel, QuizSourceModel, LessonModel):
                await conn.run_sync(model.__table__.create)
        participants, answers = _class()
        async with sessions() as db:
            db.add(LessonModel(id="l1", tutor_id="t1", discipline="Banco de Dados",
                               title="Aula 3"))
            db.add(_quiz())
            db.add(QuizSourceModel(quiz_id="quiz", source_type="lesson",
                                   source_id="l1", label="Aula 3"))
            db.add(QuizModel(id="alheio", tutor_id="outro", lesson_id="l1",
                             titulo="Alheio", status="open", total_questoes=0))
            db.add_all(_questions())
            db.add_all(participants)
            db.add_all(answers)
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


@pytest.mark.integration
def test_endpoint_devolve_o_relatorio_do_quiz(api):
    resposta = api.get("/education/quiz/quiz/report")

    assert resposta.status_code == 200
    rel = resposta.json()
    assert [a["nome"] for a in rel["alunos"]] == ["Ana", "Bia", "Caio"]
    assert rel["resumo"]["taxa_acerto"] == 75.0
    assert rel["quiz"]["disciplinas"] == ["Banco de Dados"]
    assert rel["quiz"]["fontes"] == ["Aula 3"]
    assert rel["perguntas"][0]["distribuicao"][0]["quantidade"] == 1


@pytest.mark.integration
def test_endpoint_nao_abre_quiz_de_outro_professor_nem_inexistente(api):
    assert api.get("/education/quiz/alheio/report").status_code == 404
    assert api.get("/education/quiz/nao-existe/report").status_code == 404
