import asyncio
from types import SimpleNamespace

from app.core.database import ClassGroupModel
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

    def all(self):
        return self._rows


class FakeDb:
    """Primeira consulta traz os alunos, a segunda os vinculos da aula."""

    def __init__(self, students, links=()):
        self.students = students
        self.links = list(links)
        self.calls = 0

    async def execute(self, _query):
        self.calls += 1
        return _Result(self.students if self.calls == 1 else self.links)


TURMA_3001 = ClassGroupModel(
    id="c1", tutor_id="t1", code="3001", name="Presencial", discipline="ARA0040"
)
TURMA_3002 = ClassGroupModel(
    id="c2", tutor_id="t1", code="3002", name="Semipresencial", discipline="ARA0040"
)


def _student(name, class_id=None, class_group="", discipline=""):
    return SimpleNamespace(
        id=name.lower(),
        name=name,
        class_id=class_id,
        class_group=class_group,
        discipline=discipline,
        aliases=[],
    )


def _lesson(class_group="", discipline="ARA0040"):
    return SimpleNamespace(
        id="l1", tutor_id="t1", class_group=class_group, discipline=discipline
    )


STUDENTS = [
    _student("Ana", "c1", "3001 Presencial", "ARA0040"),
    _student("Thiago", "c2", "3002 Semipresencial", "ARA0040"),
    _student("Carla", "c3", "4001", "ARA0031"),
    _student("Sem turma"),
]


def _names(links):
    rows = [(link, group) for link, group in links]
    roster = run(education._roster(_lesson(), FakeDb(STUDENTS, rows)))
    return [item["name"] for item in roster]


def test_lesson_linked_to_one_class_sees_only_that_class():
    assert _names([("l1", TURMA_3001)]) == ["Ana", "Sem turma"]


def test_joint_lesson_sees_the_students_of_every_linked_class():
    assert _names([("l1", TURMA_3001), ("l1", TURMA_3002)]) == [
        "Ana",
        "Thiago",
        "Sem turma",
    ]


def test_student_of_another_class_stays_out():
    assert "Carla" not in _names([("l1", TURMA_3001), ("l1", TURMA_3002)])


def test_lesson_without_links_falls_back_to_the_text_fields():
    # Aula anterior a tabela de turmas, com a turma so no texto.
    lesson = SimpleNamespace(
        id="l1", tutor_id="t1", class_group="3001 Presencial", discipline="ARA0040"
    )
    roster = run(education._roster(lesson, FakeDb(STUDENTS, [])))

    assert [item["name"] for item in roster] == ["Ana", "Sem turma"]
