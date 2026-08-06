import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.schemas import (
    StudentImportItem,
    StudentImportRequest,
)
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
    def __init__(self, existing=None):
        self.existing = list(existing or [])
        self.added = []
        self.committed = False

    async def execute(self, _query):
        return _Result(self.existing)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True


def _request(*rows):
    return StudentImportRequest(
        class_group="3A",
        subject="Matematica",
        students=[
            StudentImportItem(enrollment=enrollment, name=name)
            for enrollment, name in rows
        ],
    )


def test_import_creates_new_students_and_updates_existing_by_enrollment():
    existing = SimpleNamespace(
        external_id="1001",
        name="Nome antigo",
        class_group="2A",
        subject="Fisica",
        active=False,
    )
    db = FakeDb([existing])

    response = run(
        education.import_students(
            _request(("1001", "Ana Silva"), ("1002", "Bruno Lima")),
            {"tutor_id": "tutor-1"},
            db,
        )
    )

    assert response.created == 1
    assert response.updated == 1
    assert response.total == 2
    assert existing.name == "Ana Silva"
    assert existing.class_group == "3A"
    assert existing.subject == "Matematica"
    assert existing.active is True
    assert db.added[0].external_id == "1002"
    assert db.added[0].tutor_id == "tutor-1"
    assert db.committed is True


def test_import_rejects_duplicate_enrollment_in_same_file():
    db = FakeDb()

    with pytest.raises(HTTPException) as exc_info:
        run(
            education.import_students(
                _request(("1001", "Ana"), ("1001", "Outra Ana")),
                {"tutor_id": "tutor-1"},
                db,
            )
        )

    assert exc_info.value.status_code == 422
    assert "duplicada" in exc_info.value.detail
    assert db.committed is False


def test_import_requires_class_and_subject():
    body = StudentImportRequest(
        class_group="",
        subject="",
        students=[StudentImportItem(enrollment="1001", name="Ana")],
    )

    with pytest.raises(HTTPException) as exc_info:
        run(
            education.import_students(
                body,
                {"tutor_id": "tutor-1"},
                FakeDb(),
            )
        )

    assert exc_info.value.status_code == 422
    assert "Turma" in exc_info.value.detail
