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


class _MaterialsInspector:
    """Inspector com a tabela de material e o tipo atual de `content`."""

    def __init__(self, content_type="TEXT", table=True):
        self.content_type = content_type
        self.table = table

    def get_table_names(self):
        return ["materials"] if self.table else []

    def get_columns(self, _table_name):
        return [
            {"name": "id", "type": "VARCHAR(64)"},
            {"name": "content", "type": self.content_type},
        ]


class _Connection:
    def __init__(self, dialect="mysql"):
        self.dialect = type("D", (), {"name": dialect})()
        self.statements = []

    def execute(self, statement):
        self.statements.append(" ".join(str(statement).split()))


def test_material_antigo_em_text_e_ampliado(monkeypatch):
    # TEXT guarda 64 KB: a primeira apostila de verdade ja voltava
    # "Data too long for column 'content'" no INSERT.
    monkeypatch.setattr(database, "inspect", lambda _c: _MaterialsInspector("TEXT"))
    connection = _Connection()

    database._widen_material_content(connection)

    assert connection.statements == [
        "ALTER TABLE materials MODIFY COLUMN content MEDIUMTEXT NOT NULL"
    ]


def test_material_ja_ampliado_nao_roda_de_novo(monkeypatch):
    # A migracao roda a cada boot; repetir o ALTER reescreveria a tabela toda.
    monkeypatch.setattr(
        database, "inspect", lambda _c: _MaterialsInspector("MEDIUMTEXT")
    )
    connection = _Connection()

    database._widen_material_content(connection)

    assert connection.statements == []


def test_sqlite_nao_recebe_sintaxe_de_mysql(monkeypatch):
    monkeypatch.setattr(database, "inspect", lambda _c: _MaterialsInspector("TEXT"))
    connection = _Connection(dialect="sqlite")

    database._widen_material_content(connection)

    assert connection.statements == []


def test_tabela_de_material_ainda_inexistente_e_ignorada(monkeypatch):
    monkeypatch.setattr(
        database, "inspect", lambda _c: _MaterialsInspector(table=False)
    )
    connection = _Connection()

    database._widen_material_content(connection)

    assert connection.statements == []


def test_alter_concorrente_nao_derruba_o_boot(monkeypatch):
    # Dois workers sobem juntos: o segundo ALTER falha, mas a coluna ja esta
    # certa - derrubar o boot por isso seria pior que ignorar.
    inspections = iter(
        [
            _MaterialsInspector("TEXT"),
            _MaterialsInspector("MEDIUMTEXT"),
        ]
    )
    monkeypatch.setattr(database, "inspect", lambda _c: next(inspections))

    class _Racing(_Connection):
        def execute(self, statement):
            super().execute(statement)
            raise OperationalError(str(statement), {}, Exception("lock wait"))

    connection = _Racing()

    database._widen_material_content(connection)

    assert len(connection.statements) == 1


def test_alter_que_falhou_de_verdade_interrompe_o_boot(monkeypatch):
    monkeypatch.setattr(database, "inspect", lambda _c: _MaterialsInspector("TEXT"))

    class _Racing(_Connection):
        def execute(self, statement):
            super().execute(statement)
            raise OperationalError(str(statement), {}, Exception("sem permissao"))

    with pytest.raises(OperationalError):
        database._widen_material_content(_Racing())
