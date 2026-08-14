import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.schemas import LessonSegmentUpdate
from app.routers import education


def run(coro):
    return asyncio.run(coro)


class _Result:
    def __init__(self, rows=()):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class QueryDb:
    def __init__(self):
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)
        return _Result()


def test_active_class_list_excludes_closed_disciplines():
    db = QueryDb()

    assert run(
        education.list_classes(
            active_only=True,
            user={"tutor_id": "t1"},
            db=db,
        )
    ) == []

    sql = str(db.queries[0].compile(compile_kwargs={"literal_binds": True}))
    assert "class_groups.active IS true" in sql
    assert "disciplines.active IS true" in sql
    assert "class_groups.discipline_id IN" in sql


class SegmentDb:
    def __init__(self, lesson, segment):
        self.lesson = lesson
        self.segment = segment
        self.commits = 0

    async def get(self, model, item_id):
        if model is education.LessonModel and item_id == self.lesson.id:
            return self.lesson
        if model is education.LessonSegmentModel and item_id == self.segment.id:
            return self.segment
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, _item):
        pass


def _lesson():
    return SimpleNamespace(
        id="l1",
        tutor_id="t1",
        discipline="ARA0040 - BANCO DE DADOS",
        title="Normalizacao",
        class_group="3001",
        started_at=datetime(2026, 8, 14, 18, 30, tzinfo=timezone.utc),
        transcript_chars=18,
        summary="resumo antigo",
        summary_llm="gpt",
        summary_at=datetime.now(timezone.utc),
    )


def _segment():
    return SimpleNamespace(
        id="s1",
        lesson_id="l1",
        tutor_id="t1",
        sequence=1,
        text="normalizacao errda",
        confidence=0.8,
        duration_ms=60000,
        indexed=True,
        qdrant_point_id="s1",
        embedding_model="local:minilm",
        created_at=datetime.now(timezone.utc),
    )


def test_correcting_segment_updates_search_and_invalidates_summary(monkeypatch):
    lesson = _lesson()
    segment = _segment()
    db = SegmentDb(lesson, segment)
    indexed = []

    async def _index(**kwargs):
        indexed.append(kwargs)
        return 1

    monkeypatch.setattr(education.qdrant_service, "index_lesson_segments", _index)
    monkeypatch.setattr(
        education.embedding_service,
        "active_signature",
        lambda: "local:minilm",
    )

    response = run(
        education.update_lesson_segment(
            "l1",
            "s1",
            LessonSegmentUpdate(text="normalizacao correta"),
            user={"tutor_id": "t1"},
            db=db,
        )
    )

    assert response.text == "normalizacao correta"
    assert response.indexed is True
    assert lesson.transcript_chars == len("normalizacao correta")
    assert lesson.summary is None
    assert lesson.summary_llm is None
    assert lesson.summary_at is None
    assert indexed[0]["segments"][0]["text"] == "normalizacao correta"
    assert db.commits == 2


def test_cannot_correct_segment_from_another_lesson(monkeypatch):
    lesson = _lesson()
    segment = _segment()
    segment.lesson_id = "l2"

    with pytest.raises(HTTPException) as exc_info:
        run(
            education.update_lesson_segment(
                "l1",
                "s1",
                LessonSegmentUpdate(text="texto correto"),
                user={"tutor_id": "t1"},
                db=SegmentDb(lesson, segment),
            )
        )

    assert exc_info.value.status_code == 404
