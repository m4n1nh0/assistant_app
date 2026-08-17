import asyncio

from app.core.database import StudentModel
from app.routers.education import create_presentation_demo


class FakeDb:
    def __init__(self):
        self.rows = {}
        self.commits = 0

    async def get(self, model, row_id):
        return self.rows.get((model, row_id))

    def add(self, row):
        self.rows[(type(row), row.id)] = row

    async def commit(self):
        self.commits += 1


def run(coro):
    return asyncio.run(coro)


def test_presentation_demo_is_complete_and_idempotent():
    db = FakeDb()
    user = {"tutor_id": "tutor-demo"}

    first = run(create_presentation_demo(user=user, db=db))
    second = run(create_presentation_demo(user=user, db=db))

    assert first["semester"]
    assert first["discipline_created"] is True
    assert first["class_created"] is True
    assert first["students_created"] == 3
    assert first["students_updated"] == 0
    assert second["discipline_created"] is False
    assert second["class_created"] is False
    assert second["students_created"] == 0
    assert second["students_updated"] == 0
    assert first["class_id"] == second["class_id"]

    students = [
        row
        for (model, _row_id), row in db.rows.items()
        if model is StudentModel
    ]
    assert {student.external_id for student in students} == {
        "2026001",
        "2026002",
        "2026003",
    }


def test_presentation_demo_updates_legacy_enrollments_without_duplicates():
    db = FakeDb()
    user = {"tutor_id": "tutor-demo"}

    run(create_presentation_demo(user=user, db=db))
    students = [
        row
        for (model, _row_id), row in db.rows.items()
        if model is StudentModel
    ]
    for index, student in enumerate(students, start=1):
        student.external_id = f"DEMO{index:03d}"

    result = run(create_presentation_demo(user=user, db=db))

    assert result["students_created"] == 0
    assert result["students_updated"] == 3
    assert len(students) == 3
    assert {student.external_id for student in students} == {
        "2026001",
        "2026002",
        "2026003",
    }
