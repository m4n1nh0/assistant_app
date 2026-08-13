import asyncio
from datetime import datetime, timezone

from app.routers import education


def run(coro):
    return asyncio.run(coro)


class _Result:
    """Devolve as tuplas (ponto, turma) do join com a aula."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    async def execute(self, query):
        self.sql = str(query)
        return _Result(self.rows)


def _point(name, points, subject="ARA0040", lesson_id="l1", day=13):
    return education.LessonPointModel(
        id=f"{name}-{lesson_id}",
        tutor_id="t1",
        lesson_id=lesson_id,
        student_name=name,
        points=points,
        subject=subject,
        lesson_date=datetime(2026, 8, day, 19, 0, tzinfo=timezone.utc),
        source="extracted",
        confidence=1.0,
        created_at=datetime(2026, 8, day, 19, 0, tzinfo=timezone.utc),
    )


USER = {"tutor_id": "t1"}


def test_same_subject_and_day_split_by_class_group():
    db = FakeDb(
        [
            (_point("Ana", 1.0, lesson_id="l1"), "3001 PRESENCIAL"),
            (_point("Thiago", 0.5, lesson_id="l2"), "3002 SEMIPRESENCIAL"),
        ]
    )

    report = run(education.points_report(user=USER, db=db))

    assert report.total_points == 1.5
    assert [(entry.student_name, entry.class_group) for entry in report.students] == [
        ("Ana", "3001 PRESENCIAL"),
        ("Thiago", "3002 SEMIPRESENCIAL"),
    ]


def test_points_of_the_same_class_are_summed():
    db = FakeDb(
        [
            (_point("Ana", 1.0, lesson_id="l1"), "3001"),
            (_point("Ana", 0.5, lesson_id="l1"), "3001"),
        ]
    )

    report = run(education.points_report(user=USER, db=db))

    assert len(report.students) == 1
    assert report.students[0].total_points == 1.5
    assert report.students[0].class_group == "3001"


def test_orphan_point_keeps_an_empty_class_group():
    """Aula apagada: o outer join devolve turma nula e o relatorio segue."""
    db = FakeDb([(_point("Ana", 1.0), None)])

    report = run(education.points_report(user=USER, db=db))

    assert report.students[0].class_group == ""


def test_class_group_comes_from_the_lesson_by_outer_join():
    """A turma nao existe em lesson_points: sai do join com lessons, e ele
    precisa ser externo para nao sumir com ponto de aula apagada."""
    db = FakeDb([(_point("Ana", 1.0), "3001")])

    run(education.points_report(user=USER, db=db, class_group="3001"))

    sql = " ".join(db.sql.split())
    assert "LEFT OUTER JOIN lessons ON lessons.id = lesson_points.lesson_id" in sql
    assert "lessons.class_group =" in sql


def test_filter_is_echoed_in_the_response():
    db = FakeDb([(_point("Ana", 1.0), "3001")])

    report = run(education.points_report(user=USER, db=db, class_group="3001"))

    assert report.class_group == "3001"


def test_student_name_filter_still_applies_over_the_join():
    db = FakeDb(
        [
            (_point("Ana Paula", 1.0), "3001"),
            (_point("Thiago", 1.0), "3001"),
        ]
    )

    report = run(education.points_report(user=USER, db=db, student_name="ana"))

    assert [entry.student_name for entry in report.students] == ["Ana Paula"]
