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


def _row(name, points, student_group=None, lesson_group=None, **kwargs):
    """Linha do join: ponto, turma do aluno, turma da aula."""
    return (_point(name, points, **kwargs), student_group, lesson_group)


def _point(name, points, discipline="ARA0040", lesson_id="l1", day=13):
    return education.LessonPointModel(
        id=f"{name}-{lesson_id}",
        tutor_id="t1",
        lesson_id=lesson_id,
        student_name=name,
        points=points,
        discipline=discipline,
        lesson_date=datetime(2026, 8, day, 19, 0, tzinfo=timezone.utc),
        source="extracted",
        confidence=1.0,
        created_at=datetime(2026, 8, day, 19, 0, tzinfo=timezone.utc),
    )


USER = {"tutor_id": "t1"}


def test_same_discipline_and_day_split_by_class_group():
    db = FakeDb(
        [
            _row("Ana", 1.0, lesson_group="3001 PRESENCIAL", lesson_id="l1"),
            _row("Thiago", 0.5, lesson_group="3002 SEMIPRESENCIAL", lesson_id="l2"),
        ]
    )

    report = run(education.points_report(user=USER, db=db))

    assert report.total_points == 1.5
    assert [(entry.student_name, entry.class_group) for entry in report.students] == [
        ("Ana", "3001 PRESENCIAL"),
        ("Thiago", "3002 SEMIPRESENCIAL"),
    ]


def test_joint_lesson_splits_by_the_class_of_each_student():
    """Aula de turmas reunidas nao tem turma propria: quem separa e o cadastro
    do aluno."""
    db = FakeDb(
        [
            _row("Ana", 1.0, student_group="3001 PRESENCIAL", lesson_group=""),
            _row("Thiago", 1.0, student_group="3002 SEMIPRESENCIAL", lesson_group=""),
        ]
    )

    report = run(education.points_report(user=USER, db=db))

    assert [entry.class_group for entry in report.students] == [
        "3001 PRESENCIAL",
        "3002 SEMIPRESENCIAL",
    ]


def test_student_class_wins_over_the_lesson_class():
    db = FakeDb([_row("Ana", 1.0, student_group="3002", lesson_group="3001")])

    report = run(education.points_report(user=USER, db=db))

    assert report.students[0].class_group == "3002"


def test_points_of_the_same_class_are_summed():
    db = FakeDb(
        [
            _row("Ana", 1.0, student_group="3001", lesson_id="l1"),
            _row("Ana", 0.5, student_group="3001", lesson_id="l1"),
        ]
    )

    report = run(education.points_report(user=USER, db=db))

    assert len(report.students) == 1
    assert report.students[0].total_points == 1.5
    assert report.students[0].class_group == "3001"


def test_orphan_point_keeps_an_empty_class_group():
    """Aula apagada e nome sem cadastro: os dois outer joins voltam nulos e o
    relatorio segue com a turma vazia."""
    db = FakeDb([_row("Ana", 1.0)])

    report = run(education.points_report(user=USER, db=db))

    assert report.students[0].class_group == ""


def test_class_group_comes_from_outer_joins():
    """A turma nao existe em lesson_points. Os joins precisam ser externos ou
    o ponto de aula apagada, ou de nome sem cadastro, sumiria do relatorio."""
    db = FakeDb([_row("Ana", 1.0, student_group="3001")])

    run(education.points_report(user=USER, db=db))

    sql = " ".join(db.sql.split())
    assert "LEFT OUTER JOIN students ON students.id = lesson_points.student_id" in sql
    assert "LEFT OUTER JOIN lessons ON lessons.id = lesson_points.lesson_id" in sql


def test_class_group_filter_keeps_only_that_class():
    db = FakeDb(
        [
            _row("Ana", 1.0, student_group="3001"),
            _row("Thiago", 1.0, student_group="3002"),
        ]
    )

    report = run(education.points_report(user=USER, db=db, class_group="3001"))

    assert [entry.student_name for entry in report.students] == ["Ana"]
    assert report.total_points == 1.0


def test_filter_is_echoed_in_the_response():
    db = FakeDb([_row("Ana", 1.0, student_group="3001")])

    report = run(education.points_report(user=USER, db=db, class_group="3001"))

    assert report.class_group == "3001"


def test_student_name_filter_still_applies_over_the_join():
    db = FakeDb(
        [
            _row("Ana Paula", 1.0, student_group="3001"),
            _row("Thiago", 1.0, student_group="3001"),
        ]
    )

    report = run(education.points_report(user=USER, db=db, student_name="ana"))

    assert [entry.student_name for entry in report.students] == ["Ana Paula"]
