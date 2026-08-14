"""Regressoes das adicoes de colunas em bancos de versoes anteriores."""

import pytest
from sqlalchemy.exc import OperationalError

from app.core import database


class FakeInspector:
    def __init__(self, columns):
        self.columns = columns

    def get_table_names(self):
        return list(self.columns)

    def get_columns(self, table_name):
        return [{"name": name} for name in self.columns[table_name]]

    def get_indexes(self, _table_name):
        return [{"unique": True, "column_names": ["email"]}]


class RacingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        raise OperationalError(sql, {}, Exception("duplicate column"))


def test_concurrent_column_addition_does_not_fail_startup(monkeypatch):
    inspections = iter(
        [
            FakeInspector({"lesson_segments": ["id"]}),
            FakeInspector({"lesson_segments": ["id", "embedding_model"]}),
            FakeInspector({"lesson_segments": ["id", "embedding_model"]}),
        ]
    )
    monkeypatch.setattr(database, "inspect", lambda _conn: next(inspections))
    connection = RacingConnection()

    database._add_compatibility_columns(connection)

    assert connection.statements == [
        "ALTER TABLE lesson_segments "
        "ADD COLUMN embedding_model VARCHAR(120) NULL"
    ]


def test_column_addition_error_is_raised_when_column_is_still_missing(monkeypatch):
    monkeypatch.setattr(
        database,
        "inspect",
        lambda _conn: FakeInspector({"lesson_segments": ["id"]}),
    )

    with pytest.raises(OperationalError):
        database._add_compatibility_columns(RacingConnection())
