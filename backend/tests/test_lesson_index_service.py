import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import lesson_index_service as service


def run(coro):
    return asyncio.run(coro)


class _Result:
    def __init__(self, value):
        self._value = value

    def all(self):
        return self._value

    def scalar(self):
        return self._value


class FakeDb:
    """Devolve, em ordem, o que foi enfileirado para cada execute()."""

    def __init__(self, *results):
        self.results = list(results)
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _query):
        return _Result(self.results.pop(0) if self.results else [])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _lesson(lesson_id="l1"):
    return SimpleNamespace(
        id=lesson_id,
        tutor_id="t1",
        discipline="ARA0040 - BANCO DE DADOS",
        class_group="3001 Presencial",
        started_at=datetime(2026, 8, 13, 18, 30, tzinfo=timezone.utc),
    )


def _segment(segment_id, lesson_id="l1", sequence=1):
    return SimpleNamespace(
        id=segment_id,
        lesson_id=lesson_id,
        tutor_id="t1",
        sequence=sequence,
        text=f"trecho {segment_id}",
        indexed=False,
        qdrant_point_id=None,
        embedding_model=None,
    )


@pytest.fixture(autouse=True)
def clean_state():
    service.reset_cooldown()
    yield
    service.reset_cooldown()


@pytest.fixture
def semantic(monkeypatch):
    monkeypatch.setattr(service, "current_signature", _signature("local:minilm"))
    return "local:minilm"


def _signature(value):
    async def _resolve():
        return value
    return _resolve


class _Written(list):
    """Lista dos pontos gravados, com o registro das recriacoes da colecao."""
    rebuilds: list


def _indexer(monkeypatch, *, fails_on=(), mismatch=False):
    """Substitui a escrita no Qdrant, guardando o que teria sido gravado."""
    written = _Written()
    rebuilds = []

    async def _index(*, tutor_id, lesson_id, discipline, segments):
        if lesson_id in fails_on:
            raise RuntimeError("Qdrant fora do ar")
        written.append({"lesson_id": lesson_id, "segments": segments})
        return len(segments)

    async def _ensure():
        if mismatch and not rebuilds:
            raise service.qdrant_service.LessonCollectionMismatch(
                "a colecao tem vetores de 1536 dimensoes e o provedor gera 384"
            )
        return 384

    async def _rebuild():
        rebuilds.append(1)
        return 384

    monkeypatch.setattr(service.qdrant_service, "index_lesson_segments", _index)
    monkeypatch.setattr(service.qdrant_service, "ensure_lesson_collection", _ensure)
    monkeypatch.setattr(service.qdrant_service, "rebuild_lesson_collection", _rebuild)
    written.rebuilds = rebuilds
    return written


# --- Reindexacao -----------------------------------------------------------


def test_reindex_writes_pending_segments_and_stamps_the_model(
    monkeypatch, semantic
):
    written = _indexer(monkeypatch)
    lesson = _lesson()
    segments = [_segment("s1"), _segment("s2", sequence=2)]
    db = FakeDb([(segment, lesson) for segment in segments], 0)

    outcome = run(service.reindex(db, tutor_id="t1"))

    assert outcome["indexed"] == 2
    assert outcome["pending"] == 0
    assert outcome["embedding"] == "local:minilm"
    # O MySQL passa a saber que aquele trecho ja tem vetor, e de qual modelo.
    assert all(segment.indexed for segment in segments)
    assert all(segment.embedding_model == "local:minilm" for segment in segments)
    assert all(segment.qdrant_point_id == segment.id for segment in segments)
    assert written[0]["segments"][0]["text"] == "trecho s1"


def test_reindex_sends_the_lesson_metadata_with_each_segment(
    monkeypatch, semantic
):
    written = _indexer(monkeypatch)
    db = FakeDb([(_segment("s1"), _lesson())], 0)

    run(service.reindex(db, tutor_id="t1"))

    point = written[0]["segments"][0]
    assert point["class_group"] == "3001 Presencial"
    assert point["lesson_date"] == "2026-08-13"
    assert point["lesson_ts"] > 0


def test_one_lesson_failing_does_not_stop_the_others(monkeypatch, semantic):
    written = _indexer(monkeypatch, fails_on={"l1"})
    rows = [
        (_segment("s1", "l1"), _lesson("l1")),
        (_segment("s2", "l2"), _lesson("l2")),
    ]
    db = FakeDb(rows, 1)

    outcome = run(service.reindex(db, tutor_id="t1"))

    assert outcome["indexed"] == 1
    assert outcome["failed"] == 1
    assert outcome["pending"] == 1
    assert [item["lesson_id"] for item in written] == ["l2"]
    assert db.rollbacks == 1


def test_reindex_without_any_embedding_provider_reports_the_reason(monkeypatch):
    monkeypatch.setattr(service, "current_signature", _signature(""))
    db = FakeDb(3)

    outcome = run(service.reindex(db, tutor_id="t1"))

    assert outcome["indexed"] == 0
    assert outcome["pending"] == 3
    assert "provedor" in outcome["error"]


def test_dimension_mismatch_is_reported_instead_of_dropping_vectors(
    monkeypatch, semantic
):
    written = _indexer(monkeypatch, mismatch=True)
    db = FakeDb(7)

    outcome = run(service.reindex(db, tutor_id="t1"))

    # Trocar de modelo invalida a colecao inteira. Apagar por conta propria
    # seria destrutivo demais: o backend explica e espera o pedido explicito.
    assert outcome["indexed"] == 0
    assert "1536 dimensoes" in outcome["error"]
    assert written.rebuilds == []


def test_forced_reindex_rebuilds_the_collection_and_refills_it(
    monkeypatch, semantic
):
    written = _indexer(monkeypatch, mismatch=True)
    segment = _segment("s1")
    db = FakeDb(None, [(segment, _lesson())], 0)

    outcome = run(service.reindex(db, tutor_id="t1", force=True))

    assert written.rebuilds == [1]
    assert outcome["indexed"] == 1
    assert segment.embedding_model == "local:minilm"


# --- Criterio do que esta atrasado -----------------------------------------


def _sql(condition) -> str:
    return str(condition.compile(compile_kwargs={"literal_binds": True}))


def test_hash_does_not_mark_semantic_vectors_as_stale():
    # Com o hash ativo, so entra na fila o que nunca foi indexado: reescrever
    # um vetor bom com hash pioraria a busca em vez de consertar.
    sql = _sql(service._stale_condition("hash:hash"))

    assert "indexed" in sql
    assert "embedding_model" not in sql


def test_changing_the_model_marks_the_old_vectors_as_stale():
    # Modelo semantico novo: o que foi indexado por outro modelo precisa voltar.
    sql = _sql(service._stale_condition("local:minilm"))

    assert "embedding_model IS NULL" in sql
    assert "embedding_model != 'local:minilm'" in sql


# --- Reindexacao automatica ------------------------------------------------


def _session_factory(db):
    class _Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    return lambda: _Session()


def test_catch_up_skips_when_the_index_is_up_to_date(monkeypatch, semantic):
    db = FakeDb(0)
    monkeypatch.setattr(service, "AsyncSessionLocal", _session_factory(db))
    called = _indexer(monkeypatch)

    outcome = run(service.catch_up(tutor_id="t1"))

    assert outcome["indexed"] == 0
    assert outcome["skipped"] == "indice em dia"
    assert called == []


def test_catch_up_indexes_what_is_missing(monkeypatch, semantic):
    db = FakeDb(1, [(_segment("s1"), _lesson())], 0)
    monkeypatch.setattr(service, "AsyncSessionLocal", _session_factory(db))
    written = _indexer(monkeypatch)

    outcome = run(service.catch_up(tutor_id="t1", reason="teste"))

    assert outcome["indexed"] == 1
    assert len(written) == 1


def test_catch_up_respects_the_minimum_interval(monkeypatch, semantic):
    monkeypatch.setattr(service, "AsyncSessionLocal", _session_factory(FakeDb(0)))
    _indexer(monkeypatch)

    run(service.catch_up(tutor_id="t1"))
    second = run(service.catch_up(tutor_id="t1"))

    # Pergunta sem resposta e comum; nao pode virar reindexacao a cada mensagem.
    assert second["skipped"] == "intervalo minimo"
