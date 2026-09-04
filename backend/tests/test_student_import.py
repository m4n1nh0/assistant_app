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
        discipline="Matematica",
        students=[
            StudentImportItem(enrollment=enrollment, name=name)
            for enrollment, name in rows
        ],
    )


def test_import_creates_new_students_and_updates_existing_by_enrollment():
    existing = SimpleNamespace(
        external_id="1001",
        name="Nome antigo",
        class_id=None,
        class_group="2A",
        discipline="Fisica",
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
    assert existing.discipline == "Matematica"
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


def test_import_requires_class_and_discipline():
    body = StudentImportRequest(
        class_group="",
        discipline="",
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


class QueueDb(FakeDb):
    """Responde uma lista diferente por consulta, na ordem em que chegam.

    O import faz duas: a turma que ja existe e, quando ha ausentes, os alunos a
    desativar.
    """

    def __init__(self, batches):
        super().__init__()
        self.batches = list(batches)
        self.queries = []

    async def execute(self, query):
        self.queries.append(str(query))
        rows = self.batches.pop(0) if self.batches else []
        return _Result(rows)


def _student(student_id, enrollment, *, class_id=None, active=True):
    return SimpleNamespace(
        id=student_id,
        external_id=enrollment,
        name=f"Aluno {enrollment}",
        class_id=class_id,
        class_group="3A",
        discipline="Matematica",
        active=active,
    )


def test_import_procura_matricula_dentro_da_turma():
    """Aluno em duas disciplinas nao pode ser movido pela importacao da outra.

    `class_id` e uma coluna so: casando a matricula no tutor inteiro, importar a
    turma de Cloud levava o aluno embora da turma de Banco de Dados.
    """
    db = QueueDb([[]])

    run(
        education.import_students(
            _request(("1001", "Ana Silva")),
            {"tutor_id": "tutor-1"},
            db,
        )
    )

    consulta = db.queries[0]
    assert "students.class_group" in consulta
    assert "students.discipline" in consulta


def test_ausente_do_arquivo_e_desativado_e_nao_apagado():
    ausente = _student("s-9", "9999")
    db = QueueDb([[], [ausente]])

    response = run(
        education.import_students(
            StudentImportRequest(
                class_group="3A",
                discipline="Matematica",
                students=[StudentImportItem(enrollment="1001", name="Ana")],
                deactivate_ids=["s-9"],
            ),
            {"tutor_id": "tutor-1"},
            db,
        )
    )

    assert response.deactivated == 1
    # Continua existindo: presenca e pontos referenciam o id sem chave
    # estrangeira, e apagar deixaria esse historico orfao.
    assert ausente.active is False


def test_quem_esta_no_arquivo_nunca_e_desativado():
    presente = _student("s-1", "1001")
    db = QueueDb([[], [presente]])

    response = run(
        education.import_students(
            StudentImportRequest(
                class_group="3A",
                discipline="Matematica",
                students=[StudentImportItem(enrollment="1001", name="Ana")],
                # A interface pediu, mas o servidor e quem decide.
                deactivate_ids=["s-1"],
            ),
            {"tutor_id": "tutor-1"},
            db,
        )
    )

    assert response.deactivated == 0
    assert presente.active is True


def test_desativar_duas_vezes_nao_conta_duas_vezes():
    ja_inativo = _student("s-9", "9999", active=False)
    db = QueueDb([[], [ja_inativo]])

    response = run(
        education.import_students(
            StudentImportRequest(
                class_group="3A",
                discipline="Matematica",
                students=[StudentImportItem(enrollment="1001", name="Ana")],
                deactivate_ids=["s-9"],
            ),
            {"tutor_id": "tutor-1"},
            db,
        )
    )

    assert response.deactivated == 0
