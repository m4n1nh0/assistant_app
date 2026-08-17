import asyncio
from types import SimpleNamespace

from app.models.schemas import StudentBulkDeleteRequest
from app.routers import education


def run(coro):
    return asyncio.run(coro)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class FakeDb:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.deleted = []
        self.query = None
        self.committed = False

    async def execute(self, query):
        self.query = query
        return _Result(self.rows)

    async def delete(self, item):
        self.deleted.append(item)

    async def commit(self):
        self.committed = True


def test_bulk_delete_is_scoped_to_tutor_and_class_and_deduplicates_ids():
    students = [SimpleNamespace(id="student-1"), SimpleNamespace(id="student-2")]
    db = FakeDb(students)

    result = run(
        education.bulk_delete_students(
            StudentBulkDeleteRequest(
                class_id="class-1",
                student_ids=["student-1", "student-2", "student-1"],
            ),
            {"tutor_id": "tutor-1"},
            db,
        )
    )

    sql = str(db.query)
    assert "students.tutor_id" in sql
    assert "students.class_id" in sql
    assert "students.id IN" in sql
    assert result.requested == 2
    assert result.deleted == 2
    assert db.deleted == students
    assert db.committed is True


def test_bulk_delete_reports_stale_students_without_touching_other_records():
    db = FakeDb()

    result = run(
        education.bulk_delete_students(
            StudentBulkDeleteRequest(
                class_id="class-1",
                student_ids=["missing-student"],
            ),
            {"tutor_id": "tutor-1"},
            db,
        )
    )

    assert result.requested == 1
    assert result.deleted == 0
    assert db.deleted == []
    assert db.committed is True
