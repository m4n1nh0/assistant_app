"""Migracao que renomeia o antigo `subject` para `discipline`."""

from app.core import database


class FakeInspector:
    def __init__(self, tables):
        self.tables = tables

    def get_table_names(self):
        return list(self.tables)

    def get_columns(self, table_name):
        return [{"name": name} for name in self.tables[table_name]]


class FakeConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(" ".join(str(statement).split()))


def run_migration(monkeypatch, tables):
    monkeypatch.setattr(database, "inspect", lambda _conn: FakeInspector(tables))
    conn = FakeConn()
    database._rename_subject_to_discipline(conn)
    return conn.statements


OLD_SCHEMA = {
    "subjects": ["id", "tutor_id", "code", "name"],
    "lessons": ["id", "subject", "title", "class_group"],
    "students": ["id", "name", "class_id", "class_group", "subject"],
    "lesson_points": ["id", "student_name", "points", "subject"],
    "class_groups": ["id", "code", "name", "subject_id", "subject"],
}


def test_renames_table_and_every_column(monkeypatch):
    statements = run_migration(monkeypatch, dict(OLD_SCHEMA))

    assert "ALTER TABLE subjects RENAME TO disciplines" in statements
    for table in ("lessons", "students", "lesson_points", "class_groups"):
        assert (
            f"ALTER TABLE {table} RENAME COLUMN subject TO discipline" in statements
        )
    assert (
        "ALTER TABLE class_groups RENAME COLUMN subject_id TO discipline_id"
        in statements
    )


def test_second_run_does_nothing(monkeypatch):
    already_renamed = {
        "disciplines": ["id", "tutor_id", "code", "name"],
        "lessons": ["id", "discipline", "title", "class_group"],
        "students": ["id", "name", "class_id", "class_group", "discipline"],
        "lesson_points": ["id", "student_name", "points", "discipline"],
        "class_groups": ["id", "code", "name", "discipline_id", "discipline"],
    }

    assert run_migration(monkeypatch, already_renamed) == []


def test_fresh_install_has_nothing_to_rename(monkeypatch):
    assert run_migration(monkeypatch, {}) == []


def test_missing_table_is_skipped(monkeypatch):
    # Instalacao que nunca usou o modo educacao: so `lessons` existe.
    statements = run_migration(monkeypatch, {"lessons": ["id", "subject"]})

    assert statements == ["ALTER TABLE lessons RENAME COLUMN subject TO discipline"]


def test_table_rename_is_skipped_when_the_new_one_exists(monkeypatch):
    tables = dict(OLD_SCHEMA)
    tables["disciplines"] = ["id", "code"]

    statements = run_migration(monkeypatch, tables)

    assert "ALTER TABLE subjects RENAME TO disciplines" not in statements
