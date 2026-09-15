"""Ancoragem da pergunta no cadastro de aulas, antes da busca vetorial.

Os testes rodam contra um SQLite de verdade porque o que esta em jogo e a
consulta: disciplina casada por nome parcial, data no fuso do professor e
transcricao existente sao decisoes que um fake de sessao nao exercita.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    DisciplineModel,
    LessonModel,
    LessonSegmentModel,
)
from app.services import lesson_context_service as service

pytestmark = pytest.mark.integration

# Terca-feira, 15:00 em Sao Paulo (18:00 UTC).
NOW = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)


@asynccontextmanager
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for model in (DisciplineModel, LessonModel, LessonSegmentModel):
            await conn.run_sync(model.__table__.create)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        await engine.dispose()


async def add_discipline(db, *, code="ARA0040", name="BANCO DE DADOS", tutor="t1"):
    db.add(DisciplineModel(tutor_id=tutor, code=code, name=name, active=True))
    await db.commit()


async def add_lesson(
    db,
    *,
    lesson_id="l1",
    tutor="t1",
    discipline="ARA0040 - BANCO DE DADOS",
    started_at=datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc),
    segments=("normalizacao de tabelas", "chave estrangeira"),
    summary="",
    class_group="3001",
):
    db.add(LessonModel(
        id=lesson_id,
        tutor_id=tutor,
        discipline=discipline,
        class_group=class_group,
        title="",
        status="finished",
        started_at=started_at.replace(tzinfo=None),
        summary=summary or None,
    ))
    for index, text in enumerate(segments):
        db.add(LessonSegmentModel(
            id=f"{lesson_id}-s{index}",
            lesson_id=lesson_id,
            tutor_id=tutor,
            sequence=index,
            text=text,
        ))
    await db.commit()


def resolve(db, message, **kwargs):
    return service.resolve(
        db, tutor_id="t1", message=message, now=NOW, **kwargs
    )


def test_discipline_is_matched_by_the_words_the_professor_uses():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            # A aula da noite de 14/09 em Sao Paulo ja e 15/09 em UTC: e o fuso
            # do professor que decide de que dia ela e.
            await add_lesson(db)

            scope = await resolve(db, "Sobre minha aula de banco de dados hoje 14/09")

            assert scope.disciplines == ("ARA0040 - BANCO DE DADOS",)
            assert scope.day.isoformat() == "2026-09-14"
            assert [item.lesson_id for item in scope.lessons] == ["l1"]
            assert scope.lesson_ids == ("l1",)
            assert scope.lessons[0].segments == 2
    asyncio.run(scenario())


def test_discipline_is_matched_by_the_code_too():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db)

            scope = await resolve(db, "o que caiu em ARA0040 ontem?")

            assert scope.disciplines == ("ARA0040 - BANCO DE DADOS",)
            assert scope.day_label == "ontem"
            assert scope.lesson_ids == ("l1",)
    asyncio.run(scenario())


def test_a_day_without_class_reports_the_last_one_instead_of_guessing():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db)

            scope = await resolve(db, "a aula de banco de dados de hoje")

            assert scope.day.isoformat() == "2026-09-15"
            assert scope.lessons == ()
            assert scope.latest is not None
            assert scope.latest.day.isoformat() == "2026-09-14"

            text = service.describe(scope)
            assert "Nenhuma aula registrada nessa data" in text
            assert "14/09/2026" in text
            assert "nao descreva" in text or "em vez de supor" in text
    asyncio.run(scenario())


def test_a_discipline_outside_the_catalog_is_reported_as_such():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db)

            scope = await resolve(db, "a aula de calculo de ontem")

            text = service.describe(scope)
            assert "Nenhuma disciplina do cadastro foi reconhecida" in text
            assert "ARA0040 - BANCO DE DADOS" in text
    asyncio.run(scenario())


def test_a_class_without_transcript_does_not_become_a_source():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db, segments=())

            scope = await resolve(db, "resumo da aula de banco de dados de ontem")

            assert scope.lessons and scope.transcribed == ()
            assert scope.lesson_ids == ()
            assert "sem transcricao gravada" in service.describe(scope)
    asyncio.run(scenario())


def test_another_professor_never_reaches_this_scope():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db, tutor="outro")

            scope = await resolve(db, "aula de banco de dados de ontem")

            assert scope.lessons == ()
    asyncio.run(scenario())


def test_question_without_date_uses_the_recent_classes_of_the_discipline():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db, lesson_id="antiga",
                             started_at=datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc))
            await add_lesson(db, lesson_id="recente",
                             started_at=datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc))
            await add_lesson(db, lesson_id="outra",
                             discipline="ARA0062 - ESTRUTURA DE DADOS",
                             started_at=datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc))

            scope = await resolve(db, "o que ja vimos de indices em banco de dados?")

            assert set(scope.lesson_ids) == {"antiga", "recente"}
    asyncio.run(scenario())


def test_question_only_about_a_day_takes_every_class_of_that_day():
    async def scenario():
        async with database() as db:
            await add_lesson(db, lesson_id="manha",
                             started_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc))
            await add_lesson(db, lesson_id="noite",
                             started_at=datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc))

            scope = await resolve(db, "o que eu dei ontem?")

            assert set(scope.lesson_ids) == {"manha", "noite"}
    asyncio.run(scenario())


def test_a_plain_question_does_not_touch_the_lesson_tables():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db)

            scope = await resolve(db, "bom dia, tudo bem?")

            assert scope.lessons == () and scope.day is None
            assert scope.catalog == ("ARA0040 - BANCO DE DADOS",)
            assert not scope.anchored
    asyncio.run(scenario())


def test_transcript_is_read_from_the_database_when_the_index_is_behind():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db)
            scope = await resolve(db, "aula de banco de dados de ontem")

            chunks = await service.transcript_chunks(db, scope, limit=6)

            assert [chunk.content for chunk in chunks] == [
                "normalizacao de tabelas",
                "chave estrangeira",
            ]
            assert "14/09/2026" in chunks[0].reference
    asyncio.run(scenario())


def test_the_generated_summary_enters_as_context():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db, summary="Aula sobre normalizacao ate a 3FN.")
            scope = await resolve(db, "aula de banco de dados de ontem")

            chunks = service.summary_chunks(scope)

            assert chunks[0].content == "Aula sobre normalizacao ate a 3FN."
            assert "resumo da aula" in chunks[0].reference
    asyncio.run(scenario())


def test_the_class_named_earlier_in_the_conversation_is_inherited():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db)

            scope = await resolve(
                db,
                "voce poderia acessar os dados de transcricao da aula?",
                context=["Sobre minha aula de banco de dados de 14/09, me ajuda?"],
            )

            assert scope.disciplines == ("ARA0040 - BANCO DE DADOS",)
            assert scope.day.isoformat() == "2026-09-14"
            assert scope.inherited is True
            assert "confirme com o usuario" in service.describe(scope)
    asyncio.run(scenario())


def test_what_the_message_itself_says_wins_over_the_conversation():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_discipline(db, code="ARA0062", name="ESTRUTURA DE DADOS")
            await add_lesson(db)

            scope = await resolve(
                db,
                "e na aula de estrutura de dados?",
                context=["minha aula de banco de dados de 14/09"],
            )

            assert scope.disciplines == ("ARA0062 - ESTRUTURA DE DADOS",)
            assert scope.inherited is False
    asyncio.run(scenario())


def test_without_conversation_context_nothing_is_inherited():
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db)

            scope = await resolve(db, "voce poderia acessar a transcricao?")

            assert scope.disciplines == () and scope.day is None
    asyncio.run(scenario())


def test_a_long_class_is_sampled_from_end_to_end():
    # Os primeiros trechos de uma aula sao chamada e avisos: cortar o comeco
    # devolveria justamente a parte que nao responde nada.
    async def scenario():
        async with database() as db:
            await add_discipline(db)
            await add_lesson(db, segments=tuple(f"trecho {i:02d}" for i in range(20)))
            scope = await resolve(db, "aula de banco de dados de ontem")

            chunks = await service.transcript_chunks(db, scope, limit=4)

            contents = [chunk.content for chunk in chunks]
            assert len(contents) == 4
            assert contents[0] == "trecho 00"
            assert contents[-1] == "trecho 15"
    asyncio.run(scenario())


@pytest.mark.unit
@pytest.mark.parametrize(
    "message, expected",
    [
        ("me ajuda com a descricao da atividade", True),
        ("do que tratou a aula?", True),
        ("voce poderia acessar a transcricao da aula?", True),
        ("me passa o resumo", True),
        ("o professor citou chave estrangeira?", False),
        ("como funciona uma left join?", False),
    ],
)
def test_overview_requests_are_told_apart_from_pointed_ones(message, expected):
    assert service.wants_overview(message) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "message, expected",
    [
        ("e a atividade?", True),
        ("me da mais detalhes", True),
        ("detalha isso", True),
        ("explica melhor", True),
        # O acento cai na normalizacao: "qual e a capital" nao pode virar
        # referencia a uma aula so por conter "e a".
        ("qual e a capital da Franca?", False),
        ("qual é a capital da França?", False),
        ("escreve um script de backup para mim", False),
    ],
)
def test_follow_up_markers_do_not_catch_unrelated_questions(message, expected):
    assert service.is_follow_up(message) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "message, expected",
    [
        ("a aula de hoje", "2026-09-15"),
        ("a aula de ontem", "2026-09-14"),
        ("anteontem teve prova", "2026-09-13"),
        ("na aula do dia 11", "2026-09-11"),
        ("aula de 14/09", "2026-09-14"),
        ("aula de 14/09/2025", "2025-09-14"),
        ("aula de 2026-09-01", "2026-09-01"),
        # Terca e o proprio dia; segunda e a de ontem, nao a da semana que vem.
        ("o que falei na segunda", "2026-09-14"),
        ("o que falei na terca", "2026-09-15"),
    ],
)
def test_dates_are_read_in_the_professors_timezone(message, expected):
    day, _ = service.parse_day(message, now=NOW)

    assert day.isoformat() == expected


@pytest.mark.unit
def test_a_written_date_wins_over_the_word():
    # "minha aula de hoje 14/09" as 00h de 15/09: o numero e o que o usuario
    # quis dizer, e e por ele que a aula e encontrada.
    day, label = service.parse_day(
        "minha aula de hoje 14/09",
        now=datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc),
    )

    assert day.isoformat() == "2026-09-14" and label == ""


@pytest.mark.unit
def test_a_question_without_a_date_returns_none():
    assert service.parse_day("o que e normalizacao?", now=NOW) == (None, "")
