"""Prazo por pergunta e ranking acumulado do quiz ao vivo.

O que estes testes guardam veio do uso em sala:

- o ranking da rodada mostrava so os pontos da ultima pergunta, e a turma nao via
  quem estava na frente no total;
- o professor precisava encerrar cada pergunta na mao. Com o prazo escolhido, a
  pergunta fecha sozinha e o professor so chama a proxima depois do ranking;
- o painel do professor mostrava o enunciado sem as alternativas.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    QuestionModel,
    QuizModel,
    QuizParticipantModel,
    StudentAnswerModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education, quiz_play, quiz_websocket
from app.services import quiz_live_service

QUIZ = "quiz-prazo"
BASE = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
OPCOES = (
    '[{"label": "A", "texto": "3FN", "correta": true},'
    ' {"label": "B", "texto": "1FN", "correta": false}]'
)
PLAY = f"/education/quiz/{QUIZ}/play?lang=pt"
USER = {"uid": "u1", "tutor_id": "t1"}


def _answer(question_id, student, name, correct, points):
    return StudentAnswerModel(
        id=f"{question_id}-{student}",
        question_id=question_id,
        student_id=student,
        student_name=name,
        resposta="A",
        correta=correct,
        pontuacao=points,
    )


# --- unidade ---------------------------------------------------------------


@pytest.mark.unit
def test_ranking_ordena_pelo_acumulado_e_traz_os_pontos_da_pergunta():
    respostas = [
        _answer("p1", "ana", "Ana", True, 900),
        _answer("p1", "bia", "Bia", True, 400),
        _answer("p2", "ana", "Ana", True, 100),
        _answer("p2", "bia", "Bia", True, 800),
    ]

    linhas = quiz_live_service.ranking_rows(respostas, "p2")

    # Bia fez mais pontos na pergunta 2, mas Ana lidera no total: 1000 x 1200.
    assert [linha["student_name"] for linha in linhas] == ["Bia", "Ana"]
    assert [linha["score"] for linha in linhas] == [1200, 1000]
    assert [linha["round_score"] for linha in linhas] == [800, 100]
    assert [linha["position"] for linha in linhas] == [1, 2]


@pytest.mark.unit
def test_ranking_sem_pergunta_atual_nao_inventa_pontos_da_rodada():
    linhas = quiz_live_service.ranking_rows([_answer("p1", "ana", "Ana", True, 500)])

    assert linhas[0]["score"] == 500
    assert linhas[0]["round_score"] == 0
    assert linhas[0]["round_correct"] is None


@pytest.mark.unit
def test_ranking_da_pagina_publica_continua_igual_para_quem_nao_passa_pergunta():
    # Compatibilidade: `_ranking_rows(answers)` e usado por testes e chamadores
    # que nao conhecem a pergunta atual.
    linhas = quiz_play._ranking_rows([_answer("p1", "ana", "Ana", True, 500)])

    assert linhas[0]["position"] == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "valor, esperado",
    [(None, 0), (0, 0), (-5, 0), (1, 5), (4, 5), (30, 30), (999, 600), ("20", 20), ("x", 0)],
)
def test_prazo_e_normalizado_para_a_faixa_aceita(valor, esperado):
    assert quiz_live_service.normalize_time_limit(valor) == esperado


@pytest.mark.unit
def test_pontuacao_usa_o_prazo_da_pergunta_como_janela_de_velocidade():
    # 10s de 60s ainda e resposta rapida; 10s de 15s ja e perto do fim.
    com_prazo_longo = quiz_live_service.score_answer(
        correta=True, elapsed_ms=10_000, time_limit_seconds=60
    )
    com_prazo_curto = quiz_live_service.score_answer(
        correta=True, elapsed_ms=10_000, time_limit_seconds=15
    )
    sem_prazo = quiz_live_service.score_answer(correta=True, elapsed_ms=10_000)

    assert com_prazo_longo > sem_prazo > com_prazo_curto
    assert quiz_live_service.score_answer(correta=False, elapsed_ms=1, time_limit_seconds=60) == 0


@pytest.mark.unit
def test_segundos_restantes_so_existem_com_pergunta_aberta_e_prazo():
    agora = datetime.now(timezone.utc)
    aberta = SimpleNamespace(
        live_phase="question", question_ends_at=agora + timedelta(seconds=20)
    )
    manual = SimpleNamespace(live_phase="question", question_ends_at=None)
    encerrada = SimpleNamespace(
        live_phase="results", question_ends_at=agora + timedelta(seconds=20)
    )

    assert 19 <= quiz_live_service.seconds_remaining(aberta) <= 20
    assert quiz_live_service.seconds_remaining(manual) is None
    assert quiz_live_service.seconds_remaining(encerrada) is None


# --- integracao: tela do aluno, monitor e comandos do professor ------------


@pytest.fixture
def sala():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/quiz.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, StudentAnswerModel, QuizParticipantModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                QuizModel(id=QUIZ, tutor_id="t1", lesson_id="l1", titulo="Modelagem",
                          status="open", live_phase="lobby", total_questoes=2),
                QuestionModel(id="p1", quiz_id=QUIZ, tipo="multipla_escolha",
                              enunciado="Primeira pergunta?", opcoes=OPCOES,
                              resposta_correta="A", created_at=BASE),
                QuestionModel(id="p2", quiz_id=QUIZ, tipo="multipla_escolha",
                              enunciado="Segunda pergunta?", opcoes=OPCOES,
                              resposta_correta="A",
                              created_at=BASE + timedelta(seconds=1)),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(quiz_play.router)
    app.include_router(education.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER

    def abrir(question_id, *, termina_em=None, limite=0, fase="question"):
        """Poe o quiz numa pergunta aberta, com o prazo `termina_em` segundos a frente."""

        async def update():
            async with sessions() as db:
                quiz = await db.get(QuizModel, QUIZ)
                agora = datetime.now(timezone.utc)
                quiz.live_phase = fase
                quiz.current_question_id = question_id
                quiz.question_started_at = agora
                quiz.time_limit_seconds = limite
                quiz.question_ends_at = (
                    agora + timedelta(seconds=termina_em) if termina_em is not None else None
                )
                await db.commit()

        asyncio.run(update())

    def stats():
        async def read():
            async with sessions() as db:
                return await quiz_websocket.get_quiz_stats(QUIZ, db)

        return asyncio.run(read())

    def quiz():
        async def read():
            async with sessions() as db:
                return await db.get(QuizModel, QUIZ)

        return asyncio.run(read())

    def responder(student_id, name, question_id, correct, points):
        async def write():
            async with sessions() as db:
                db.add(_answer(question_id, student_id, name, correct, points))
                await db.commit()

        asyncio.run(write())

    with TestClient(app) as client:
        client.abrir = abrir
        client.stats = stats
        client.quiz = quiz
        client.responder = responder
        yield client
    asyncio.run(engine.dispose())


def entrar(client, nome="Mariano"):
    return client.post(PLAY, data={"student_name": nome}, follow_redirects=False)


@pytest.mark.integration
def test_pergunta_com_prazo_vencido_fecha_sozinha_e_mostra_o_ranking(sala):
    entrar(sala)
    # Prazo estourou ha 10s: ja passou a folga de rede.
    sala.abrir("p1", termina_em=-10, limite=15)

    estado = sala.get(f"/education/quiz/{QUIZ}/state").json()

    assert estado["live_phase"] == "results"
    assert estado["current_question_id"] == "p1", "a pergunta segue marcada: e dela o ranking"
    assert sala.quiz().live_phase == "results"
    pagina = sala.get(PLAY).text
    assert "Ranking" in pagina


@pytest.mark.integration
def test_pergunta_dentro_do_prazo_continua_aberta_e_mostra_o_relogio(sala):
    entrar(sala)
    sala.abrir("p1", termina_em=40, limite=45)

    estado = sala.get(f"/education/quiz/{QUIZ}/state").json()
    pagina = sala.get(PLAY).text

    assert estado["live_phase"] == "question"
    assert 38 <= estado["seconds_remaining"] <= 40
    assert 'class="timer-label"' in pagina
    assert "s restantes" in pagina


@pytest.mark.integration
def test_pergunta_sem_prazo_nao_mostra_relogio_nem_fecha_sozinha(sala):
    entrar(sala)
    sala.abrir("p1", termina_em=None, limite=0)

    estado = sala.get(f"/education/quiz/{QUIZ}/state").json()
    pagina = sala.get(PLAY).text

    assert estado["live_phase"] == "question"
    assert estado["seconds_remaining"] is None
    assert "timer-label" not in pagina


@pytest.mark.integration
def test_resposta_no_ultimo_segundo_ainda_vale_pela_folga_de_rede(sala):
    entrar(sala)
    # O relogio zerou ha 1s: dentro da folga, a resposta que estava na rede vale.
    sala.abrir("p1", termina_em=-1, limite=15)

    sala.post(PLAY, data={"question_id": "p1", "answer": "A"}, follow_redirects=False)

    assert sala.stats()["progress"]["total_answers"] == 1


@pytest.mark.integration
def test_resposta_depois_do_prazo_e_da_folga_nao_e_gravada(sala):
    entrar(sala)
    sala.abrir("p1", termina_em=-30, limite=15)

    sala.post(PLAY, data={"question_id": "p1", "answer": "A"}, follow_redirects=False)

    assert sala.stats()["progress"]["total_answers"] == 0
    assert sala.quiz().live_phase == "results"


@pytest.mark.integration
def test_monitor_fecha_a_pergunta_vencida_e_manda_o_ranking_acumulado(sala):
    sala.responder("ana", "Ana", "p1", True, 900)
    sala.responder("bia", "Bia", "p1", True, 400)
    sala.responder("ana", "Ana", "p2", True, 100)
    sala.responder("bia", "Bia", "p2", True, 800)
    sala.abrir("p2", termina_em=-10, limite=15)

    numeros = sala.stats()

    assert numeros["live_phase"] == "results"
    assert numeros["time_limit_seconds"] == 15
    ranking = numeros["ranking_top10"]
    assert [linha["student_name"] for linha in ranking] == ["Bia", "Ana"]
    assert [linha["score"] for linha in ranking] == [1200, 1000]
    assert [linha["round_score"] for linha in ranking] == [800, 100]


@pytest.mark.integration
def test_monitor_mostra_alternativas_e_so_revela_o_gabarito_depois_do_prazo(sala):
    sala.abrir("p1", termina_em=60, limite=60)
    durante = sala.stats()["current_question"]

    assert [item["texto"] for item in durante["options"]] == ["3FN", "1FN"]
    assert all("correta" not in item for item in durante["options"]), (
        "o painel costuma estar projetado: gabarito so depois de encerrar"
    )

    sala.abrir("p1", termina_em=60, limite=60, fase="results")
    depois = sala.stats()["current_question"]

    assert [item["correta"] for item in depois["options"]] == [True, False]


@pytest.mark.integration
def test_pagina_de_ranking_do_aluno_mostra_acumulado_e_pontos_da_pergunta(sala):
    entrar(sala, "Ana")
    # O aluno do teste e o dono do cookie: pega o id da tentativa dele.
    tentativa = sala.cookies[quiz_play._attempt_cookie_name(QUIZ)]
    sala.responder(tentativa, "Ana", "p1", True, 900)
    sala.responder(tentativa, "Ana", "p2", True, 300)
    sala.responder("bia", "Bia", "p1", True, 400)
    sala.responder("bia", "Bia", "p2", False, 0)
    sala.abrir("p2", termina_em=None, fase="results")

    pagina = sala.get(PLAY).text

    assert "1200 pontos" in pagina, "acumulado de Ana: 900 + 300"
    assert "+300 nesta pergunta" in pagina
    assert "Você acertou" in pagina
    assert "A próxima pergunta aparecerá quando o professor liberar." in pagina


@pytest.mark.integration
def test_professor_define_o_prazo_e_a_proxima_pergunta_guarda_o_relogio(sala):
    definido = sala.post(f"/education/quiz/{QUIZ}/settings", json={"time_limit_seconds": 20})
    assert definido.status_code == 200
    assert definido.json()["time_limit_seconds"] == 20

    aberta = sala.post(f"/education/quiz/{QUIZ}/next-question").json()

    assert aberta["live_phase"] == "question"
    assert 18 <= aberta["seconds_remaining"] <= 20

    # Mudar o prazo no meio da rodada nao mexe na pergunta que ja esta no ar.
    sala.post(f"/education/quiz/{QUIZ}/settings", json={"time_limit_seconds": 120})
    assert 15 <= sala.get(f"/education/quiz/{QUIZ}").json()["seconds_remaining"] <= 20

    # A proxima pergunta ja abre com o prazo novo.
    sala.post(f"/education/quiz/{QUIZ}/close-question")
    proxima = sala.post(f"/education/quiz/{QUIZ}/next-question").json()
    assert 118 <= proxima["seconds_remaining"] <= 120


@pytest.mark.integration
def test_prazo_zero_volta_ao_modo_manual(sala):
    sala.post(f"/education/quiz/{QUIZ}/settings", json={"time_limit_seconds": 30})
    sala.post(f"/education/quiz/{QUIZ}/settings", json={"time_limit_seconds": 0})

    aberta = sala.post(f"/education/quiz/{QUIZ}/next-question").json()

    assert aberta["time_limit_seconds"] == 0
    assert aberta["seconds_remaining"] is None


@pytest.mark.integration
def test_prazo_fora_da_faixa_e_recusado(sala):
    assert sala.post(
        f"/education/quiz/{QUIZ}/settings", json={"time_limit_seconds": 601}
    ).status_code == 422
    assert sala.post(
        f"/education/quiz/{QUIZ}/settings", json={"time_limit_seconds": -1}
    ).status_code == 422


@pytest.mark.integration
def test_encerrar_pergunta_que_o_relogio_ja_encerrou_nao_vira_erro(sala):
    sala.abrir("p1", termina_em=-30, limite=15)

    resposta = sala.post(f"/education/quiz/{QUIZ}/close-question")

    assert resposta.status_code == 200
    assert resposta.json()["live_phase"] == "results"


@pytest.mark.integration
def test_pergunta_nova_nao_e_fechada_por_leitor_com_o_quiz_velho(sala):
    """O professor abre a pergunta 2 enquanto alguem ainda tem a 1 em maos."""

    async def corrida():
        async with sala_sessions(sala)() as leitor:
            quiz_velho = await leitor.get(QuizModel, QUIZ)
            # Professor abre a pergunta 2, por outra sessao, com prazo longo.
            async with sala_sessions(sala)() as professor:
                quiz = await professor.get(QuizModel, QUIZ)
                agora = datetime.now(timezone.utc)
                quiz.live_phase = "question"
                quiz.current_question_id = "p2"
                quiz.question_started_at = agora
                quiz.question_ends_at = agora + timedelta(seconds=60)
                await professor.commit()
            # O leitor ainda acha que a pergunta 1 venceu.
            quiz_velho.current_question_id = "p1"
            quiz_velho.question_ends_at = datetime.now(timezone.utc) - timedelta(seconds=30)
            return await quiz_live_service.expire_question_if_due(leitor, quiz_velho)

    assert asyncio.run(corrida()) is False
    assert sala.quiz().live_phase == "question"
    assert sala.quiz().current_question_id == "p2"


def sala_sessions(client):
    """Fabrica de sessoes do app de teste (a mesma que o fixture injeta)."""
    override = client.app.dependency_overrides[get_db]

    class Fabrica:
        def __call__(self):
            generator = override()

            class Contexto:
                async def __aenter__(self_inner):
                    self_inner.session = await generator.__anext__()
                    return self_inner.session

                async def __aexit__(self_inner, *exc):
                    await generator.aclose()

            return Contexto()

    return Fabrica()
