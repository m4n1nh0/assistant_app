"""Fila de geracao de quiz e banco de questoes.

A fila roda contra SQLite de verdade porque o que esta em jogo e persistencia:
pedido que sobrevive a reinicio, uma geracao por professor, cancelamento que
grava o estado certo. O gerador e trocado por um dublê - a IA tem teste proprio.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import (
    LessonModel,
    MaterialModel,
    QuestionModel,
    QuizJobModel,
    QuizModel,
    QuizSourceModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education
from app.services.quiz_job_service import QuizQueue

pytestmark = pytest.mark.integration


def make_engine():
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


async def create_tables(engine):
    async with engine.begin() as conn:
        for model in (QuizJobModel, QuizModel, QuizSourceModel, QuestionModel, LessonModel, MaterialModel):
            await conn.run_sync(model.__table__.create)


def pedido(**extra):
    return {"lesson_id": "lesson-1", "quantidade_questoes": 3, **extra}


# --- fila ------------------------------------------------------------------


def run_queue(scenario):
    import tempfile

    async def main():
        # Arquivo, nao memoria: o worker e a requisicao usam conexoes proprias ao
        # mesmo tempo, como no MySQL. SQLite em memoria compartilharia uma so.
        pasta = tempfile.mkdtemp()
        engine = create_async_engine(f"sqlite+aiosqlite:///{pasta}/fila.db")
        await create_tables(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            return await scenario(sessions)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def test_pedido_na_fila_gera_grava_o_quiz_e_avisa():
    avisos = []

    async def runner(job, progress):
        progress(3, 3)
        return {"quiz_id": "quiz-1", "prontas": 3, "message": "3 prontas", "attempts": [{"llm": "x"}]}

    async def notifier(job):
        avisos.append((job.status, job.titulo))

    async def scenario(sessions):
        queue = QuizQueue(sessions, runner=runner, notifier=notifier)
        criado = await queue.enqueue(tutor_id="t1", user_id="u1", titulo="Quiz: Aula", total=3, request=pedido())
        assert criado["status"] == "queued"
        await queue.wait_idle("t1")
        return await queue.get(criado["job_id"], "t1")

    job = run_queue(scenario)

    assert job["status"] == "done"
    assert job["quiz_id"] == "quiz-1"
    assert job["prontas"] == 3
    assert job["message"] == "3 prontas"
    assert job["attempts"] == [{"llm": "x"}]
    assert job["can_review"] is True
    assert avisos == [("done", "Quiz: Aula")]


def test_uma_geracao_por_professor_e_a_ordem_do_pedido_vale():
    liberar = asyncio.Event()
    ordem = []

    async def runner(job, progress):
        ordem.append(job.titulo)
        if job.titulo == "primeiro":
            await liberar.wait()
        return {"quiz_id": job.titulo, "prontas": 1}

    async def scenario(sessions):
        queue = QuizQueue(sessions, runner=runner)
        await queue.enqueue(tutor_id="t1", user_id="", titulo="primeiro", total=1, request=pedido())
        await asyncio.sleep(0.05)
        segundo = await queue.enqueue(tutor_id="t1", user_id="", titulo="segundo", total=1, request=pedido())
        terceiro = await queue.enqueue(tutor_id="t1", user_id="", titulo="terceiro", total=1, request=pedido())
        await asyncio.sleep(0.05)
        durante = {job["titulo"]: job for job in await queue.list_jobs("t1")}
        liberar.set()
        await queue.wait_idle("t1")
        return segundo, terceiro, durante

    segundo, terceiro, durante = run_queue(scenario)

    assert ordem == ["primeiro", "segundo", "terceiro"]
    assert durante["primeiro"]["status"] == "running"
    assert durante["segundo"]["status"] == "queued"
    # Posicao conta o que esta gerando como 1.
    assert segundo["position"] == 2 and terceiro["position"] == 3
    assert "1 pedido(s) antes" in durante["segundo"]["message"]


def test_professores_diferentes_nao_esperam_um_pelo_outro():
    liberar = asyncio.Event()
    comecaram = []

    async def runner(job, progress):
        comecaram.append(job.tutor_id)
        await liberar.wait()
        return {"quiz_id": "q", "prontas": 1}

    async def scenario(sessions):
        queue = QuizQueue(sessions, runner=runner)
        await queue.enqueue(tutor_id="t1", user_id="", titulo="a", total=1, request=pedido())
        await queue.enqueue(tutor_id="t2", user_id="", titulo="b", total=1, request=pedido())
        await asyncio.sleep(0.1)
        rodando = sorted(comecaram)
        liberar.set()
        await queue.wait_idle("t1")
        await queue.wait_idle("t2")
        return rodando

    assert run_queue(scenario) == ["t1", "t2"]


def test_cancelar_pedido_na_fila_e_em_andamento_sem_avisar():
    liberar = asyncio.Event()
    avisos = []

    async def runner(job, progress):
        await liberar.wait()
        return {"quiz_id": "q", "prontas": 1}

    async def notifier(job):
        avisos.append(job.status)

    async def scenario(sessions):
        queue = QuizQueue(sessions, runner=runner, notifier=notifier)
        rodando = await queue.enqueue(tutor_id="t1", user_id="", titulo="a", total=1, request=pedido())
        await asyncio.sleep(0.05)
        esperando = await queue.enqueue(tutor_id="t1", user_id="", titulo="b", total=1, request=pedido())

        cancelado_na_fila = await queue.cancel(esperando["job_id"], "t1")
        cancelado_rodando = await queue.cancel(rodando["job_id"], "t1")
        await queue.wait_idle("t1")
        return cancelado_na_fila, cancelado_rodando

    na_fila, rodando = run_queue(scenario)

    assert na_fila["status"] == "canceled"
    assert rodando["status"] == "canceled"
    assert rodando["can_retry"] is True
    assert avisos == []


def test_falha_guarda_a_frase_para_o_professor_e_tentar_de_novo_reenfileira():
    tentativas = []

    async def runner(job, progress):
        tentativas.append(json.loads(job.request_json))
        if len(tentativas) == 1:
            raise HTTPException(status_code=502, detail="A IA não gerou perguntas válidas.")
        return {"quiz_id": "q2", "prontas": 2}

    async def scenario(sessions):
        queue = QuizQueue(sessions, runner=runner)
        primeiro = await queue.enqueue(tutor_id="t1", user_id="", titulo="a", total=2, request=pedido(dificuldade="facil"))
        await queue.wait_idle("t1")
        falhou = await queue.get(primeiro["job_id"], "t1")

        novo = await queue.retry(primeiro["job_id"], "t1")
        await queue.wait_idle("t1")
        refeito = await queue.get(novo["job_id"], "t1")

        with pytest.raises(ValueError):
            await queue.retry(novo["job_id"], "t1")
        return falhou, refeito

    falhou, refeito = run_queue(scenario)

    assert falhou["status"] == "error"
    assert falhou["error"] == "A IA não gerou perguntas válidas."
    assert refeito["status"] == "done"
    # O mesmo pedido, inclusive a configuracao escolhida.
    assert tentativas[0] == tentativas[1]
    assert tentativas[1]["dificuldade"] == "facil"


def test_pedido_que_rodava_quando_o_processo_caiu_volta_para_a_fila():
    geradas = []

    async def runner(job, progress):
        geradas.append(job.id)
        return {"quiz_id": "q", "prontas": 1}

    async def scenario(sessions):
        async with sessions() as db:
            db.add(QuizJobModel(
                id="orfao", tutor_id="t1", titulo="antes do deploy", status="running",
                total=1, request_json=json.dumps(pedido()),
                started_at=datetime.now(timezone.utc),
            ))
            await db.commit()

        queue = QuizQueue(sessions, runner=runner)
        retomados = await queue.recover()
        await queue.wait_idle("t1")
        return retomados, await queue.get("orfao", "t1")

    retomados, job = run_queue(scenario)

    assert retomados == 1
    assert geradas == ["orfao"]
    assert job["status"] == "done"


def test_aviso_visto_e_pedido_de_outro_professor():
    async def runner(job, progress):
        return {"quiz_id": "q", "prontas": 1}

    async def scenario(sessions):
        queue = QuizQueue(sessions, runner=runner)
        job = await queue.enqueue(tutor_id="t1", user_id="", titulo="a", total=1, request=pedido())
        await queue.wait_idle("t1")
        de_outro = await queue.get(job["job_id"], "t2")
        outro_marca = await queue.mark_seen("t2", [job["job_id"]])
        marcados = await queue.mark_seen("t1", [job["job_id"]])
        de_novo = await queue.mark_seen("t1", [job["job_id"]])
        return de_outro, outro_marca, marcados, de_novo, await queue.get(job["job_id"], "t1")

    de_outro, outro_marca, marcados, de_novo, job = run_queue(scenario)

    assert de_outro is None
    assert outro_marca == 0
    assert (marcados, de_novo) == (1, 0)
    assert job["seen"] is True


def test_andamento_aparece_enquanto_gera():
    liberar = asyncio.Event()

    async def runner(job, progress):
        progress(2, 5)
        await liberar.wait()
        return {"quiz_id": "q", "prontas": 5}

    async def scenario(sessions):
        queue = QuizQueue(sessions, runner=runner)
        job = await queue.enqueue(tutor_id="t1", user_id="", titulo="a", total=5, request=pedido())
        await asyncio.sleep(0.05)
        durante = await queue.get(job["job_id"], "t1")
        liberar.set()
        await queue.wait_idle("t1")
        return durante

    durante = run_queue(scenario)

    assert durante["status"] == "running"
    assert durante["prontas"] == 2
    assert "(2/5)" in durante["message"]


# --- worker da rota ---------------------------------------------------------


def test_worker_usa_as_chaves_do_banco_e_as_questoes_ja_existentes(monkeypatch):
    """O pedido roda longe da requisicao: as chaves vem do banco, nao da ContextVar."""
    from app.services import user_llm_config_service

    capturado = {}

    async def fake_runtime(tutor_id):
        capturado["runtime_tutor"] = tutor_id
        return user_llm_config_service.UserLLMRuntime(
            scope=f"tutor:{tutor_id}",
            providers={"claude": {"api_key": "k", "model": "m", "enabled": True}},
        )

    async def fake_context(request, tutor_id, db):
        return {"fontes": [{"type": "lesson", "id": "lesson-1", "label": "Aula"}]}

    async def fake_existing(db, tutor_id, fontes):
        return [{"enunciado": "Pergunta antiga?"}]

    async def fake_generation(context, *, request, tutor_id, db, on_progress, questoes_existentes):
        capturado["provedores"] = list(user_llm_config_service.runtime_settings.active_llms)
        capturado["existentes"] = questoes_existentes
        capturado["quantidade"] = request.quantidade_questoes
        return SimpleNamespace(quiz_id="quiz-9", questoes=[1, 2], message="ok", attempts=[])

    class Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(education, "load_user_llm_runtime", fake_runtime)
    monkeypatch.setattr(education, "_quiz_generation_context", fake_context)
    monkeypatch.setattr(education, "_existing_questions_for_sources", fake_existing)
    monkeypatch.setattr(education, "_run_quiz_generation", fake_generation)
    monkeypatch.setattr(education, "AsyncSessionLocal", lambda: Session())

    job = SimpleNamespace(tutor_id="t1", request_json=json.dumps(pedido()))
    resultado = asyncio.run(education._run_quiz_job(job, lambda *_: None))

    assert resultado == {"quiz_id": "quiz-9", "prontas": 2, "message": "ok", "attempts": []}
    assert capturado["runtime_tutor"] == "t1"
    assert "claude" in capturado["provedores"]
    assert capturado["existentes"] == [{"enunciado": "Pergunta antiga?"}]
    assert capturado["quantidade"] == 3
    assert user_llm_config_service.current_user_llms() is None


# --- banco de questoes -------------------------------------------------------


USER = {"uid": "u1", "tutor_id": "t1"}
AGORA = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def opcoes(correta="A"):
    return json.dumps([
        {"label": "A", "texto": "3FN", "correta": correta == "A"},
        {"label": "B", "texto": "1FN", "correta": correta == "B"},
    ])


@pytest.fixture
def banco():
    engine = make_engine()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        await create_tables(engine)
        async with sessions() as db:
            db.add_all([
                LessonModel(id="lesson-1", tutor_id="t1", discipline="BANCO DE DADOS", title="Normalizacao"),
                LessonModel(id="lesson-2", tutor_id="t1", discipline="PYTHON", title="Listas"),
                QuizModel(id="rascunho", tutor_id="t1", lesson_id="lesson-1", titulo="Quiz BD", status="draft", total_questoes=2),
                QuizModel(id="aplicado", tutor_id="t1", lesson_id="lesson-2", titulo="Quiz Python", status="closed", total_questoes=1),
                QuizModel(id="alheio", tutor_id="t2", lesson_id="lesson-x", titulo="De outro", status="draft", total_questoes=1),
                QuizSourceModel(quiz_id="rascunho", source_type="lesson", source_id="lesson-1", label="Normalizacao"),
                QuizSourceModel(quiz_id="aplicado", source_type="lesson", source_id="lesson-2", label="Listas"),
                QuestionModel(id="q1", quiz_id="rascunho", tipo="multipla_escolha", enunciado="O que elimina dependencia transitiva?",
                              opcoes=opcoes(), resposta_correta="A", justificativa="aula", topico_origem="Normalizacao", created_at=AGORA),
                QuestionModel(id="q2", quiz_id="rascunho", tipo="multipla_escolha", enunciado="O que e chave estrangeira?",
                              opcoes=opcoes("B"), resposta_correta="B", dificuldade="facil", created_at=AGORA + timedelta(seconds=1)),
                QuestionModel(id="q3", quiz_id="aplicado", tipo="multipla_escolha", enunciado="Como criar uma lista em Python?",
                              opcoes=opcoes(), resposta_correta="A", created_at=AGORA + timedelta(seconds=2)),
                QuestionModel(id="qx", quiz_id="alheio", tipo="multipla_escolha", enunciado="Pergunta de outro professor",
                              opcoes=opcoes(), resposta_correta="A", created_at=AGORA),
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


def test_lista_quizzes_com_disciplina_vinda_das_fontes(banco):
    body = banco.get("/education/quiz").json()

    por_id = {quiz["id"]: quiz for quiz in body["quizzes"]}
    assert set(por_id) == {"rascunho", "aplicado"}
    assert por_id["rascunho"]["disciplinas"] == ["BANCO DE DADOS"]
    assert por_id["rascunho"]["total_questoes"] == 2
    assert body["disciplinas"] == ["BANCO DE DADOS", "PYTHON"]

    so_python = banco.get("/education/quiz", params={"discipline": "python"}).json()
    assert [quiz["id"] for quiz in so_python["quizzes"]] == ["aplicado"]


def test_banco_filtra_por_disciplina_texto_e_dificuldade(banco):
    tudo = banco.get("/education/quiz/questions").json()
    assert tudo["total"] == 3
    assert "qx" not in {q["id"] for q in tudo["questions"]}

    bd = banco.get("/education/quiz/questions", params={"discipline": "BANCO DE DADOS"}).json()
    assert {q["id"] for q in bd["questions"]} == {"q1", "q2"}

    texto = banco.get("/education/quiz/questions", params={"q": "estrangeira"}).json()
    assert [q["id"] for q in texto["questions"]] == ["q2"]

    faceis = banco.get("/education/quiz/questions", params={"dificuldade": "facil"}).json()
    assert [q["id"] for q in faceis["questions"]] == ["q2"]

    q1 = next(q for q in bd["questions"] if q["id"] == "q1")
    assert q1["editavel"] is True
    assert q1["opcoes"][0] == {"label": "A", "texto": "3FN", "correta": True}


def test_editar_questao_de_rascunho_e_recusar_em_quiz_aplicado(banco):
    editada = banco.patch("/education/quiz/questions/q1", json={
        "enunciado": "Qual forma normal elimina dependencia transitiva?",
        "opcoes": [
            {"label": "A", "texto": "1FN", "correta": False},
            {"label": "B", "texto": "3FN", "correta": True},
        ],
    })
    assert editada.status_code == 200, editada.text
    assert editada.json()["resposta_correta"] == "B"
    assert editada.json()["verificado"] is True

    duas_corretas = banco.patch("/education/quiz/questions/q1", json={
        "opcoes": [
            {"label": "A", "texto": "1FN", "correta": True},
            {"label": "B", "texto": "3FN", "correta": True},
        ],
    })
    assert duas_corretas.status_code == 422

    aplicado = banco.patch("/education/quiz/questions/q3", json={"enunciado": "outra"})
    assert aplicado.status_code == 409

    alheia = banco.patch("/education/quiz/questions/qx", json={"enunciado": "outra"})
    assert alheia.status_code == 404


def test_excluir_apaga_no_rascunho_e_arquiva_no_quiz_aplicado(banco):
    apagada = banco.delete("/education/quiz/questions/q2").json()
    assert apagada == {"deleted": True, "archived": False}
    quizzes = {q["id"]: q for q in banco.get("/education/quiz").json()["quizzes"]}
    assert quizzes["rascunho"]["total_questoes"] == 1

    arquivada = banco.delete("/education/quiz/questions/q3").json()
    assert arquivada == {"deleted": False, "archived": True}
    visiveis = {q["id"] for q in banco.get("/education/quiz/questions").json()["questions"]}
    assert "q3" not in visiveis
    com_arquivadas = banco.get("/education/quiz/questions", params={"include_archived": True}).json()
    assert "q3" in {q["id"] for q in com_arquivadas["questions"]}

    restaurada = banco.post("/education/quiz/questions/q3/restore").json()
    assert restaurada["arquivada"] is False


def test_montar_quiz_copia_questoes_na_ordem_escolhida(banco):
    criado = banco.post("/education/quiz/from-questions", json={
        "titulo": "Simulado",
        "question_ids": ["q3", "q1"],
    })
    assert criado.status_code == 201, criado.text
    quiz = criado.json()
    assert quiz["status"] == "draft"
    assert [q["enunciado"] for q in quiz["questoes"]] == [
        "Como criar uma lista em Python?",
        "O que elimina dependencia transitiva?",
    ]
    # Copia, nao move: ids novos e o quiz de origem intacto.
    assert {q["id"] for q in quiz["questoes"]}.isdisjoint({"q1", "q3"})
    assert banco.get("/education/quiz/rascunho").json()["total_questoes"] == 2

    lista = {q["id"]: q for q in banco.get("/education/quiz").json()["quizzes"]}
    assert set(lista[quiz["id"]]["disciplinas"]) == {"PYTHON", "BANCO DE DADOS"}

    alheia = banco.post("/education/quiz/from-questions", json={"titulo": "x", "question_ids": ["qx"]})
    assert alheia.status_code == 404

    banco.delete("/education/quiz/questions/q3")
    arquivada = banco.post("/education/quiz/from-questions", json={"titulo": "x", "question_ids": ["q3"]})
    assert arquivada.status_code == 409


def test_descartar_so_rascunho(banco):
    assert banco.delete("/education/quiz/aplicado").status_code == 409
    assert banco.delete("/education/quiz/rascunho").json() == {"deleted": True}
    assert banco.get("/education/quiz/rascunho").status_code == 404


def test_questoes_existentes_das_mesmas_fontes_vao_para_a_geracao(banco):
    async def consulta():
        async with banco.sessions() as db:
            await db.execute(
                QuestionModel.__table__.update()
                .where(QuestionModel.id == "q2")
                .values(arquivada=True)
            )
            await db.commit()
            return await education._existing_questions_for_sources(
                db, "t1", [{"type": "lesson", "id": "lesson-1"}]
            )

    existentes = asyncio.run(consulta())

    assert [q["enunciado"] for q in existentes] == ["O que elimina dependencia transitiva?"]
    assert existentes[0]["opcoes"][0]["texto"] == "3FN"
    assert existentes[0]["topico_origem"] == "Normalizacao"
