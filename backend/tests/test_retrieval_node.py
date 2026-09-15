"""O no de RAG do chat, do cadastro de aulas ate o prompt que o modelo recebe.

O banco e real (SQLite em arquivo) e o vector store e um fake: o que estes
testes cobrem e a decisao do no - quando buscar, com que escopo, e o que dizer
ao modelo quando a aula nao existe -, nao a similaridade de vetor.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import database
from app.core.database import DisciplineModel, LessonModel, LessonSegmentModel
from app.orchestration.nodes.retrieval import build_retrieve_context
from app.models.schemas import Message
from app.orchestration.state import ChatRuntimeContext
from app.ports.retrieval import RetrievedChunk

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)


class FakeGateway:
    """Vector store de mentira que registra com que escopo foi chamado."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.calls: list[dict] = []

    async def search(self, query, *, tenant_id, limit=6, min_score=0.0, lesson_ids=()):
        self.calls.append({
            "query": query,
            "tenant_id": tenant_id,
            "min_score": min_score,
            "lesson_ids": tuple(lesson_ids),
        })
        return list(self.chunks)


async def _seed(db, *, with_lesson=True, segments=("normalizacao de tabelas",)):
    db.add(DisciplineModel(
        tutor_id="t1", code="ARA0040", name="BANCO DE DADOS", active=True
    ))
    if with_lesson:
        db.add(LessonModel(
            id="l1",
            tutor_id="t1",
            discipline="ARA0040 - BANCO DE DADOS",
            class_group="3001",
            status="finished",
            # 14/09 as 20h30 em Sao Paulo.
            started_at=datetime(2026, 9, 14, 23, 30),
        ))
        for index, text in enumerate(segments):
            db.add(LessonSegmentModel(
                id=f"s{index}", lesson_id="l1", tutor_id="t1",
                sequence=index, text=text,
            ))
    await db.commit()


def run_node(tmp_path, monkeypatch, message, *, gateway, history=(), seed=_seed, **seed_kwargs):
    """Roda o no com um banco de verdade e devolve o update que ele produziu."""

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lessons.db'}")
        async with engine.begin() as conn:
            for model in (DisciplineModel, LessonModel, LessonSegmentModel):
                await conn.run_sync(model.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
        try:
            async with sessions() as db:
                await seed(db, **seed_kwargs)
            node = build_retrieve_context(gateway)
            return await node(
                {"message": message, "system_prompt": "system", "history": list(history)},
                SimpleNamespace(context=ChatRuntimeContext(
                    tutor_id="t1", timezone="America/Sao_Paulo"
                )),
            )
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def test_question_about_a_class_searches_only_inside_that_class(tmp_path, monkeypatch):
    gateway = FakeGateway([
        RetrievedChunk(content="1FN, 2FN e 3FN", score=0.4, reference="BD, 14/09")
    ])

    update = run_node(
        tmp_path, monkeypatch,
        "na aula de banco de dados de 14/09, o professor citou chave estrangeira?",
        gateway=gateway,
    )

    assert gateway.calls[0]["lesson_ids"] == ("l1",)
    prompt = update["system_prompt"]
    assert "Disciplina citada na pergunta: ARA0040 - BANCO DE DADOS" in prompt
    assert "Aula registrada: ARA0040 - BANCO DE DADOS, 14/09/2026" in prompt
    assert "1 trecho(s) transcrito(s)" in prompt
    assert "1FN, 2FN e 3FN" in prompt


def test_asking_for_the_whole_class_reads_the_transcript_instead_of_top_k(tmp_path, monkeypatch):
    # O top-k responde mal a este pedido: a frase nao se parece com nenhum
    # trecho da fala do professor, entao os vizinhos mais proximos vem por acaso.
    gateway = FakeGateway([
        RetrievedChunk(content="trecho por acaso", score=0.9, reference="BD, 14/09")
    ])

    update = run_node(
        tmp_path, monkeypatch,
        "minha aula de banco de dados de 14/09: me ajuda com a descricao da atividade",
        gateway=gateway,
        segments=("chamada e avisos", "normalizacao de tabelas", "a atividade e modelar a biblioteca"),
    )

    assert gateway.calls == [], "pedido de visao geral nao deveria pagar busca vetorial"
    prompt = update["system_prompt"]
    assert "a atividade e modelar a biblioteca" in prompt
    assert "trecho por acaso" not in prompt


def test_transcript_comes_from_the_database_when_the_index_is_empty(tmp_path, monkeypatch):
    gateway = FakeGateway([])

    update = run_node(
        tmp_path, monkeypatch,
        "sobre a aula de banco de dados de 14/09, do que tratamos?",
        gateway=gateway,
    )

    assert "normalizacao de tabelas" in update["system_prompt"]


def test_a_date_without_class_is_said_out_loud(tmp_path, monkeypatch):
    gateway = FakeGateway([
        RetrievedChunk(content="trecho de outra aula", score=0.9, reference="BD, 01/08")
    ])

    update = run_node(
        tmp_path, monkeypatch,
        "o que eu dei na aula de banco de dados de 15/09?",
        gateway=gateway,
    )

    prompt = update["system_prompt"]
    assert "Nenhuma aula registrada nessa data" in prompt
    assert "Aula mais recente dessa disciplina: ARA0040 - BANCO DE DADOS, 14/09/2026" in prompt
    # Sem aula naquela data nao ha escopo: a busca larga ate roda, mas o modelo
    # foi avisado de que a aula pedida nao existe.
    assert gateway.calls[0]["lesson_ids"] == ()


def test_a_discipline_in_the_message_turns_on_rag_outside_the_study_route(tmp_path, monkeypatch):
    gateway = FakeGateway([])

    update = run_node(
        tmp_path, monkeypatch,
        "tem um bug no meu codigo python de banco de dados",
        gateway=gateway,
    )

    assert update["task_kind"] == "code"
    assert gateway.calls, "a disciplina citada deveria ligar a busca"
    assert "ARA0040 - BANCO DE DADOS" in update["system_prompt"]


def test_follow_up_keeps_the_class_named_in_the_previous_turn(tmp_path, monkeypatch):
    # O caso real: a primeira pergunta nomeia a aula, a segunda fala dela por
    # pronome. Sem herdar a ancora, a segunda perdia a aula e o assistente
    # voltava a pedir o que o usuario ja tinha dito.
    gateway = FakeGateway([])

    update = run_node(
        tmp_path, monkeypatch,
        "voce poderia acessar os dados de transcricao da aula?",
        gateway=gateway,
        history=[
            Message(role="user", content="Sobre minha aula de banco de dados de 14/09, "
                                         "pode me ajudar com a descricao da atividade?"),
            Message(role="assistant", content="Claro, preciso de mais contexto."),
        ],
    )

    prompt = update["system_prompt"]
    assert "ARA0040 - BANCO DE DADOS" in prompt
    assert "14/09/2026" in prompt
    assert "normalizacao de tabelas" in prompt
    assert "confirme com o usuario" in prompt


def test_the_anchor_is_not_inherited_by_an_unrelated_question(tmp_path, monkeypatch):
    gateway = FakeGateway([])

    update = run_node(
        tmp_path, monkeypatch,
        "qual e a capital da Franca?",
        gateway=gateway,
        history=[Message(role="user", content="minha aula de banco de dados de 14/09")],
    )

    assert gateway.calls == []
    assert "system_prompt" not in update


def test_the_model_is_told_it_already_has_the_transcript(tmp_path, monkeypatch):
    # A resposta que motivou o ajuste pedia captura de janela, porque o prompt
    # do desktop e a unica instrucao que falava em obter contexto.
    update = run_node(
        tmp_path, monkeypatch,
        "me passa a transcricao da aula de banco de dados de 14/09",
        gateway=FakeGateway([]),
    )

    prompt = update["system_prompt"]
    assert "Nunca peca captura de tela" in prompt
    assert "peca exatamente esses dois dados" in prompt


def test_small_talk_does_not_pay_for_a_vector_search(tmp_path, monkeypatch):
    gateway = FakeGateway([])

    update = run_node(tmp_path, monkeypatch, "bom dia, tudo bem?", gateway=gateway)

    assert gateway.calls == []
    assert "system_prompt" not in update


def test_a_broken_index_still_answers_with_what_the_database_confirmed(tmp_path, monkeypatch):
    class Broken(FakeGateway):
        async def search(self, *args, **kwargs):
            raise RuntimeError("qdrant fora do ar")

    update = run_node(
        tmp_path, monkeypatch,
        "aula de banco de dados de 14/09",
        gateway=Broken(),
    )

    assert "Aula registrada: ARA0040 - BANCO DE DADOS, 14/09/2026" in update["system_prompt"]
    assert any("busca de aula falhou" in error for error in update["errors"])
    # O indice caiu, mas a transcricao no banco ainda responde.
    assert "normalizacao de tabelas" in update["system_prompt"]
