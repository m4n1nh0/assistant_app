"""Atualizacao ao vivo da tela do aluno, sem recarregar a pagina inteira.

A tela se recarregava a cada 2s (meta refresh). Para quem usa leitor de tela, cada
recarga devolve a leitura ao inicio da pagina e tira o foco do teclado. Agora a
pagina consulta `/state` e so se troca quando o estado do quiz muda.

Como era o recarregamento que marcava a presenca do aluno no lobby do professor,
a consulta de estado passou a marcar - e este arquivo guarda isso tambem.
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
    QuestionModel,
    QuestionTranslationModel,
    QuizModel,
    QuizParticipantModel,
    StudentAnswerModel,
    get_db,
)
from app.routers import quiz_play, quiz_websocket

QUIZ = "quiz-ao-vivo-2"
BASE = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
OPCOES = (
    '[{"label": "A", "texto": "3FN", "correta": true},'
    ' {"label": "B", "texto": "1FN", "correta": false}]'
)
PLAY = f"/education/quiz/{QUIZ}/play"
STATE = f"/education/quiz/{QUIZ}/state"


@pytest.fixture
def sala():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/quiz.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, StudentAnswerModel,
                          QuizParticipantModel, QuestionTranslationModel):
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
                              resposta_correta="A", created_at=BASE + timedelta(seconds=1)),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(quiz_play.router)
    app.dependency_overrides[get_db] = db_dependency

    def fase(phase, question_id=None, *, status="open", restante=None):
        async def update():
            async with sessions() as db:
                quiz = await db.get(QuizModel, QUIZ)
                quiz.status = status
                quiz.live_phase = phase
                quiz.current_question_id = question_id
                agora = datetime.now(timezone.utc)
                quiz.question_started_at = agora if question_id else None
                quiz.question_ends_at = (
                    agora + timedelta(seconds=restante) if restante is not None else None
                )
                quiz.time_limit_seconds = restante or 0
                await db.commit()

        asyncio.run(update())

    def stats():
        async def read():
            async with sessions() as db:
                return await quiz_websocket.get_quiz_stats(QUIZ, db)

        return asyncio.run(read())

    def envelhecer():
        async def update():
            async with sessions() as db:
                await db.execute(
                    QuizParticipantModel.__table__.update().values(
                        last_seen_at=datetime.now(timezone.utc) - timedelta(minutes=5)
                    )
                )
                await db.commit()

        asyncio.run(update())

    def participantes():
        async def read():
            async with sessions() as db:
                from sqlalchemy import select
                return (await db.execute(select(QuizParticipantModel))).scalars().all()

        return asyncio.run(read())

    with TestClient(app) as client:
        client.fase = fase
        client.stats = stats
        client.envelhecer = envelhecer
        client.participantes = participantes
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def entrar(client, nome="Ana", idioma="pt"):
    return client.post(
        f"{PLAY}?lang=pt",
        data={"student_name": nome, "language": idioma},
        follow_redirects=False,
    )


# --- a pagina nao se recarrega mais sozinha ----------------------------------


@pytest.mark.integration
def test_pagina_de_espera_consulta_o_estado_em_vez_de_recarregar(sala):
    entrar(sala)

    pagina = sala.get(f"{PLAY}?lang=pt").text

    # O recarregamento antigo so existe como reserva para quem esta sem JavaScript.
    assert pagina.count('http-equiv="refresh"') == 1
    assert '<noscript><meta http-equiv="refresh" content="2"></noscript>' in pagina
    assert 'id="live-script"' in pagina
    assert 'data-signature="open|lobby|"' in pagina
    assert f'data-quiz="{QUIZ}"' in pagina


@pytest.mark.integration
def test_pagina_da_pergunta_carrega_a_assinatura_do_estado_e_o_relogio_para_o_script(sala):
    entrar(sala)
    sala.fase("question", "p1", restante=45)

    pagina = sala.get(f"{PLAY}?lang=pt").text

    assert 'data-signature="open|question|p1"' in pagina
    assert 'id="left" data-seconds="4' in pagina or 'id="left" data-seconds="45"' in pagina
    # O recarregamento por pergunta trocada saiu da pagina: quem troca e o script.
    assert "data.current_question_id !==" not in pagina


@pytest.mark.integration
def test_relogio_so_e_anunciado_em_marcos_e_nao_a_cada_segundo(sala):
    entrar(sala)
    sala.fase("question", "p1", restante=45)

    pagina = sala.get(f"{PLAY}?lang=pt").text

    assert "left === 10 || left === 5" in pagina
    # O numero que muda por segundo nao esta numa regiao aria-live; so a regiao
    # de anuncios, vazia, esta.
    assert 'id="live-announce" class="sr-only" role="status" aria-live="polite"' in pagina
    assert '<div class="timer" aria-hidden="true">' in pagina
    assert 'id="left" data-seconds' in pagina
    trecho_do_numero = pagina.split('id="left"')[1].split("</div>")[0]
    assert "aria-live" not in trecho_do_numero


@pytest.mark.integration
@pytest.mark.parametrize(
    "idioma, palavra",
    [("pt", "segundos restantes"), ("es", "segundos restantes"), ("en", "seconds left")],
)
def test_anuncio_do_relogio_sai_no_idioma_da_tela(sala, idioma, palavra):
    entrar(sala, idioma=idioma)
    sala.fase("question", "p1", restante=30)

    pagina = sala.get(f"{PLAY}?lang={idioma}").text

    assert f'data-unit="{palavra}"' in pagina


@pytest.mark.integration
def test_cada_tela_tem_titulo_que_recebe_o_foco_na_troca(sala):
    entrar(sala)
    espera = sala.get(f"{PLAY}?lang=pt").text
    sala.fase("question", "p1", restante=30)
    pergunta = sala.get(f"{PLAY}?lang=pt").text
    sala.fase("results", "p1")
    ranking = sala.get(f"{PLAY}?lang=pt").text

    for pagina in (espera, pergunta, ranking):
        assert '<h1 id="live-heading" tabindex="-1">' in pagina


@pytest.mark.integration
def test_ranking_entre_perguntas_continua_ao_vivo_e_o_final_nao(sala):
    entrar(sala)
    sala.fase("results", "p1")
    entre_perguntas = sala.get(f"{PLAY}?lang=pt").text
    assert 'data-signature="open|results|p1"' in entre_perguntas
    assert 'id="live-script"' in entre_perguntas

    sala.fase("finished", None)
    final = sala.get(f"{PLAY}?lang=pt").text
    # Ranking final nao muda mais: sem consulta e sem recarregamento.
    assert 'id="live-script"' not in final
    assert "http-equiv" not in final


@pytest.mark.integration
def test_resultado_do_aluno_vem_antes_da_lista_para_o_leitor_de_tela(sala):
    entrar(sala)
    tentativa = sala.cookies[quiz_play._attempt_cookie_name(QUIZ)]

    async def responder():
        async with sala.sessions() as db:
            db.add(StudentAnswerModel(
                id="r1", question_id="p1", student_id=tentativa, student_name="Ana",
                resposta="A", correta=True, pontuacao=900,
            ))
            await db.commit()

    asyncio.run(responder())
    sala.fase("results", "p1")

    pagina = sala.get(f"{PLAY}?lang=pt").text

    assert pagina.index('class="own"') < pagina.index("<ol>")

def test_assinatura_do_estado_usa_os_mesmos_padroes_do_script():
    sem_dados = QuizModel(id="q", tutor_id="t", lesson_id="l", titulo="x")
    aberta = QuizModel(id="q", tutor_id="t", lesson_id="l", titulo="x", status="open",
                       live_phase="question", current_question_id="p3")

    # O script monta a assinatura com `status || 'open'`, `live_phase || 'lobby'`
    # e `current_question_id || ''`: os padroes tem que ser os mesmos.
    assert quiz_play._state_signature(sem_dados) == "open|lobby|"
    assert quiz_play._state_signature(aberta) == "open|question|p3"


# --- a consulta de estado marca a presenca do aluno --------------------------


@pytest.mark.integration
def test_consulta_de_estado_mantem_o_aluno_online_sem_recarregar_a_pagina(sala):
    entrar(sala)
    sala.envelhecer()
    assert sala.stats()["participants_online"] == 0

    estado = sala.get(f"{STATE}?lang=pt")

    assert estado.status_code == 200
    assert sala.stats()["participants_online"] == 1


@pytest.mark.integration
def test_consulta_de_estado_anonima_nao_cria_participante(sala):
    # Sem cookie de tentativa nem de nome: ninguem entrou.
    estado = sala.get(STATE)

    assert estado.status_code == 200
    assert sala.participantes() == []


@pytest.mark.integration
def test_consulta_de_estado_nao_reabre_presenca_em_quiz_encerrado(sala):
    entrar(sala)
    sala.envelhecer()
    sala.fase("finished", None, status="closed")

    sala.get(f"{STATE}?lang=pt")

    assert sala.stats()["participants_online"] == 0


@pytest.mark.integration
def test_consulta_de_estado_leva_o_idioma_do_aluno(sala):
    entrar(sala, idioma="pt")

    sala.get(f"{STATE}?lang=es")

    assert [p.language for p in sala.participantes()] == ["es"]


@pytest.mark.integration
def test_consulta_de_estado_devolve_o_que_o_script_compara(sala):
    entrar(sala)
    sala.fase("question", "p1", restante=30)

    estado = sala.get(STATE).json()

    assert (estado["status"], estado["live_phase"], estado["current_question_id"]) == (
        "open", "question", "p1",
    )


@pytest.mark.integration
def test_script_segue_idioma_e_unidade_da_pagina_nova_depois_de_trocar(sala):
    """Achado ao executar o script num DOM simulado: depois da troca de conteudo
    ele continuava anunciando o relogio com a unidade da pagina original."""
    entrar(sala)

    pagina = sala.get(f"{PLAY}?lang=pt").text

    assert "let lang = me.dataset.lang;" in pagina
    assert "let unit = me.dataset.unit;" in pagina
    assert "unit = incoming.dataset.unit;" in pagina
    assert "lang = incoming.dataset.lang;" in pagina
