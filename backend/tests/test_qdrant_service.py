"""Memoria e aulas no Qdrant: uma colecao por natureza do dado, e o filtro faz o resto.

Roda no modo em memoria do proprio cliente do Qdrant: filtros, faixas e busca por similaridade sao
os de verdade, so sem rede. O embedding e um hash de palavras deterministico, para que "parecido"
signifique "divide palavras".
"""

import asyncio
import hashlib
import math

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.services import embedding_service, qdrant_service as q

DIMS = 32

P1 = "00000000-0000-0000-0000-000000000001"
P2 = "00000000-0000-0000-0000-000000000002"
P3 = "00000000-0000-0000-0000-000000000003"


def run(coro):
    return asyncio.run(coro)


def fake_vector(text: str) -> list[float]:
    vector = [0.0] * DIMS
    for word in text.lower().split():
        digest = hashlib.sha256(word.strip(".,?!").encode()).digest()
        vector[int.from_bytes(digest[:2], "big") % DIMS] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


@pytest.fixture(autouse=True)
def qdrant(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(q, "_client", lambda: client)
    q._INDEXED.clear()

    async def dims():
        return DIMS

    async def embed_texts(texts):
        return [fake_vector(t) for t in texts]

    async def embed_text(text):
        return fake_vector(text)

    monkeypatch.setattr(embedding_service, "resolve_dimensions", dims)
    monkeypatch.setattr(embedding_service, "embed_texts", embed_texts)
    monkeypatch.setattr(embedding_service, "embed_text", embed_text)
    monkeypatch.setattr(embedding_service, "active_signature", lambda: "test:fake")
    yield client
    q._INDEXED.clear()


def remember(**overrides):
    values = dict(
        point_id=P1,
        tutor_id="t1",
        category="tutor_preferences",
        content="prefiro respostas curtas e diretas",
    )
    values.update(overrides)
    return run(q.upsert_memory(**values))


def ids(results):
    return [r["id"] for r in results]


# --- uma colecao de memoria, nao uma por categoria --------------------------


def test_memory_is_one_collection_and_the_category_is_a_field(qdrant):
    remember(point_id=P1, category="tutor_preferences")
    remember(point_id=P2, category="behavior_guidelines", content="sempre cite a fonte")

    names = [c.name for c in qdrant.get_collections().collections]

    assert names == ["assistant_memory"]
    assert qdrant.count("assistant_memory", exact=True).count == 2


def test_search_ranks_by_similarity_and_returns_the_structured_fields():
    remember(point_id=P1, content="prefiro respostas curtas e diretas", agents=["general"], source="review")
    remember(point_id=P2, content="a turma de banco de dados usa MySQL")

    hits = run(q.search_memory(tutor_id="t1", query="respostas curtas"))

    assert ids(hits)[0] == P1
    first = hits[0]
    assert first["category"] == "tutor_preferences"
    assert first["agents"] == ["general"] and first["source"] == "review"
    assert first["score"] > hits[1]["score"]


# --- filtros ------------------------------------------------------------------


def test_one_user_never_sees_the_memory_of_another():
    remember(point_id=P1, tutor_id="t1", content="segredo do usuario um")
    remember(point_id=P2, tutor_id="t2", content="segredo do usuario dois")

    mine = run(q.search_memory(tutor_id="t1", query="segredo do usuario"))

    assert ids(mine) == [P1]


def test_category_filter_accepts_one_or_several():
    remember(point_id=P1, category="tutor_preferences", content="resposta curta")
    remember(point_id=P2, category="behavior_guidelines", content="resposta curta")
    remember(point_id=P3, category="automation_knowledge", content="resposta curta")

    one = run(q.search_memory(tutor_id="t1", query="resposta curta", categories=["behavior_guidelines"]))
    two = run(q.search_memory(tutor_id="t1", query="resposta curta",
                              categories=["tutor_preferences", "automation_knowledge"]))
    every = run(q.search_memory(tutor_id="t1", query="resposta curta"))

    assert ids(one) == [P2]
    assert sorted(ids(two)) == [P1, P3]
    assert len(every) == 3


def test_specialty_filter_sees_its_own_facts_and_the_ones_for_everybody():
    remember(point_id=P1, content="resposta curta", agents=["study"])
    remember(point_id=P2, content="resposta curta", agents=["code"])
    remember(point_id=P3, content="resposta curta")  # para todas

    study = run(q.search_memory(tutor_id="t1", query="resposta curta", agent="study"))
    code = run(q.search_memory(tutor_id="t1", query="resposta curta", agent="code"))
    anyone = run(q.search_memory(tutor_id="t1", query="resposta curta"))

    assert sorted(ids(study)) == [P1, P3]
    assert sorted(ids(code)) == [P2, P3]
    assert len(anyone) == 3  # sem especialidade, nao restringe


def test_source_and_time_filters():
    remember(point_id=P1, content="resposta curta", source="review")
    remember(point_id=P2, content="resposta curta", source="automation")

    by_source = run(q.search_memory(tutor_id="t1", query="resposta curta", source="automation"))
    future = run(q.search_memory(tutor_id="t1", query="resposta curta", since_ts=4_102_444_800))  # ano 2100
    past = run(q.search_memory(tutor_id="t1", query="resposta curta", since_ts=0))

    assert ids(by_source) == [P2]
    assert future == []
    assert len(past) == 2


def test_min_score_drops_what_is_not_similar_enough():
    remember(point_id=P1, content="prefiro respostas curtas e diretas")
    remember(point_id=P2, content="zebra girafa elefante leao")

    loose = run(q.search_memory(tutor_id="t1", query="respostas curtas"))
    strict = run(q.search_memory(tutor_id="t1", query="respostas curtas", min_score=0.3))

    assert len(loose) == 2
    assert ids(strict) == [P1]


def test_an_unknown_category_is_rejected_instead_of_matching_nothing():
    with pytest.raises(ValueError, match="Categoria inválida"):
        run(q.search_memory(tutor_id="t1", query="x", categories=["inventada"]))
    with pytest.raises(ValueError, match="Categoria inválida"):
        remember(category="inventada")


def test_memory_filter_always_carries_the_owner():
    flt = q.memory_filter("t1", categories=["tutor_preferences"], agent="study", since_ts=10, source="review")

    assert [c.key for c in flt.must] == ["tutor_id", "category", "agents", "created_ts", "source"]
    assert flt.must[0].match.value == "t1"


def test_delete_only_removes_the_owners_fact():
    remember(point_id=P1, tutor_id="t1", content="meu fato")

    run(q.delete_memory(point_id=P1, tutor_id="t2"))
    assert len(run(q.search_memory(tutor_id="t1", query="meu fato"))) == 1

    run(q.delete_memory(point_id=P1, tutor_id="t1"))
    assert run(q.search_memory(tutor_id="t1", query="meu fato")) == []


def test_upsert_is_idempotent_for_the_same_point():
    remember(point_id=P1, content="versao um")
    remember(point_id=P1, content="versao dois")

    hits = run(q.search_memory(tutor_id="t1", query="versao"))

    assert [h["content"] for h in hits] == ["versao dois"]


# --- aulas: a busca precisa realmente ler o indice --------------------------------


def lesson_segments(lesson_id, texts, *, ts_start=0):
    return [
        {"id": f"00000000-0000-0000-0000-0000{lesson_id}{i:04d}", "text": text,
         "lesson_ts": ts_start + i * 60, "sequence": i, "class_group": "turma-1", "lesson_date": "2026-10-10"}
        for i, text in enumerate(texts)
    ]


def index(tutor, lesson, discipline, texts, **kw):
    return run(q.index_lesson_segments(
        tutor_id=tutor, lesson_id=lesson, discipline=discipline, segments=lesson_segments(lesson, texts, **kw)))


def test_lesson_search_reads_the_index_instead_of_failing_silently():
    # Regressao: o cliente fixado nao tem mais `search`; a chamada antiga levantava AttributeError,
    # engolido, e a busca devolvia sempre [] sem avisar.
    index("t1", "1111", "Banco de Dados", ["indices aceleram consultas no banco", "normalizacao reduz redundancia"])

    hits = run(q.search_lesson_transcripts(tutor_id="t1", query="indices e consultas"))

    assert hits, "a busca nas aulas nao pode devolver vazio quando ha trechos indexados"
    assert hits[0]["content"].startswith("indices")
    assert hits[0]["discipline"] == "Banco de Dados"


def test_lesson_filters_by_owner_discipline_lesson_and_time_window():
    index("t1", "1111", "Banco de Dados", ["transacao garante atomicidade", "indice acelera consulta"])
    index("t1", "2222", "Redes", ["transacao de pacotes na rede", "roteador encaminha pacotes"], ts_start=1000)
    index("t2", "3333", "Banco de Dados", ["transacao do outro usuario"])

    own = run(q.search_lesson_transcripts(tutor_id="t1", query="transacao"))
    by_discipline = run(q.search_lesson_transcripts(tutor_id="t1", query="transacao", discipline="Redes"))
    by_lessons = run(q.search_lesson_transcripts(tutor_id="t1", query="transacao", lesson_ids=["1111"]))
    window = run(q.search_lesson_transcripts(tutor_id="t1", query="transacao", ts_from=1000, ts_to=1030))

    assert {h["lesson_id"] for h in own} == {"1111", "2222"}
    assert {h["lesson_id"] for h in by_discipline} == {"2222"}
    assert {h["lesson_id"] for h in by_lessons} == {"1111"}
    assert [h["content"] for h in window] == ["transacao de pacotes na rede"]


# --- indices de payload ---------------------------------------------------------------


class SpyClient:
    def __init__(self, fail_on=()):
        self.created = []
        self.fail_on = set(fail_on)

    def create_payload_index(self, *, collection_name, field_name, field_schema):
        if field_name in self.fail_on:
            raise RuntimeError("servidor recusou")
        self.created.append((collection_name, field_name))


def test_every_filtered_field_gets_a_payload_index_once():
    spy = SpyClient()

    q._ensure_payload_indexes(spy, "assistant_memory", q.MEMORY_INDEXES)
    q._ensure_payload_indexes(spy, "assistant_memory", q.MEMORY_INDEXES)

    assert sorted(f for _, f in spy.created) == sorted(q.MEMORY_INDEXES)
    assert len(spy.created) == len(q.MEMORY_INDEXES)  # a segunda chamada nao vai ao servidor


def test_the_indexes_cover_the_fields_the_filters_use():
    flt = q.memory_filter("t", categories=["tutor_preferences"], agent="a", since_ts=1, source="s")
    assert {c.key for c in flt.must} <= set(q.MEMORY_INDEXES)

    lesson = q._lesson_filter("t", "d", None, 1, 2, ["x"])
    assert {c.key for c in lesson.must} <= set(q.LESSON_INDEXES)


def test_the_owner_is_indexed_as_tenant():
    assert q.MEMORY_INDEXES["tutor_id"].is_tenant is True
    assert q.LESSON_INDEXES["tutor_id"].is_tenant is True


def test_a_failed_index_is_retried_next_time_and_does_not_break_the_search():
    spy = SpyClient(fail_on={"source"})

    q._ensure_payload_indexes(spy, "assistant_memory", q.MEMORY_INDEXES)
    assert "assistant_memory" not in q._INDEXED

    spy.fail_on.clear()
    q._ensure_payload_indexes(spy, "assistant_memory", q.MEMORY_INDEXES)
    assert "assistant_memory" in q._INDEXED


# --- dimensao ------------------------------------------------------------------------


def test_memory_collection_with_another_dimension_and_data_is_not_recreated(qdrant):
    qdrant.create_collection("assistant_memory", vectors_config=VectorParams(size=8, distance=Distance.COSINE))
    qdrant.upsert("assistant_memory", points=[PointStruct(id=P1, vector=[0.1] * 8, payload={"content": "x"})])

    with pytest.raises(q.MemoryCollectionMismatch):
        run(q.ensure_memory_collection())

    assert qdrant.count("assistant_memory", exact=True).count == 1


def test_empty_memory_collection_with_another_dimension_is_recreated(qdrant):
    qdrant.create_collection("assistant_memory", vectors_config=VectorParams(size=8, distance=Distance.COSINE))

    run(q.ensure_memory_collection())

    assert q._existing_vector_size(qdrant, "assistant_memory") == DIMS


# --- migracao das quatro colecoes antigas -----------------------------------------------


def legacy(client, category, rows):
    name = f"assistant_{category}"
    client.create_collection(name, vectors_config=VectorParams(size=DIMS, distance=Distance.COSINE))
    if rows:
        client.upsert(name, points=[
            PointStruct(id=pid, vector=[0.0] * DIMS, payload={
                "id": pid, "tutor_id": tutor, "category": category, "content": text, "metadata": {"k": "v"}})
            for pid, tutor, text in rows
        ])


def test_legacy_collections_are_migrated_and_empty_ones_dropped(qdrant):
    legacy(qdrant, "tutor_preferences", [
        (P1, "t1", "prefiro respostas curtas"),
        (P2, "t1", "trate-me por voce"),
    ])
    legacy(qdrant, "behavior_guidelines", [])

    summary = run(q.migrate_legacy_memory())

    assert summary == {"dropped_empty": 1, "migrated": 2, "failed": 0}
    names = {c.name for c in qdrant.get_collections().collections}
    assert names == {"assistant_memory"}
    hits = run(q.search_memory(tutor_id="t1", query="respostas curtas", categories=["tutor_preferences"]))
    assert hits[0]["content"] == "prefiro respostas curtas"
    assert hits[0]["source"] == "legacy-migration"
    assert hits[0]["metadata"] == {"k": "v"}


def test_a_failed_migration_keeps_the_old_collection_untouched(qdrant, monkeypatch):
    legacy(qdrant, "tutor_preferences", [(P1, "t1", "prefiro respostas curtas")])

    async def broken(texts):
        raise RuntimeError("provedor de embedding fora do ar")

    monkeypatch.setattr(embedding_service, "embed_texts", broken)

    summary = run(q.migrate_legacy_memory())

    assert summary["failed"] == 1 and summary["migrated"] == 0
    assert qdrant.count("assistant_tutor_preferences", exact=True).count == 1


def test_migration_with_nothing_legacy_is_a_no_op(qdrant):
    assert run(q.migrate_legacy_memory()) == {"dropped_empty": 0, "migrated": 0, "failed": 0}
