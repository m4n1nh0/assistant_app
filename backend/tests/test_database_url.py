"""Resolucao da URL do banco a partir do ambiente.

O caso que motivou estes testes aconteceu em deploy: `DATABASE_URL` montada com
referencias a variaveis que o servico MySQL nao publicava resolveu para
`mysql+aiomysql://:@host:3306/`, e o erro do driver ("Access denied for user
'app'") apontava para o usuario do container, nao para a variavel vazia.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.core.database import database_url_problems, resolve_database_url

pytestmark = pytest.mark.unit

DEFAULT = "mysql+aiomysql://assistant:assistant@localhost:3306/assistant"
GOOD = "mysql+aiomysql://root:segredo@mysql.railway.internal:3306/railway"


def test_complete_database_url_is_used_as_is():
    assert resolve_database_url(GOOD, {}) == GOOD


def test_empty_references_are_reported_without_the_password():
    problems = database_url_problems("mysql+aiomysql://:@mysql.railway.internal:3306/")

    assert problems == ["usuario vazio", "nome do banco vazio"]


def test_unresolved_reference_is_reported():
    url = "mysql+aiomysql://${{mysql.MYSQLUSER}}:x@host:3306/db"

    assert database_url_problems(url) == ["referencia de variavel nao resolvida (${{...}})"]


def test_broken_database_url_falls_back_to_mysql_variables():
    """Imagem oficial do MySQL publica MYSQL_USER, nao MYSQLUSER."""
    env = {
        "MYSQL_USER": "app_user",
        "MYSQL_PASSWORD": "p@ss:w/rd",
        "MYSQL_HOST": "mysql.railway.internal",
        "MYSQL_DATABASE": "assistant",
    }

    url = make_url(resolve_database_url("mysql+aiomysql://:@mysql.railway.internal:3306/", env))

    assert url.username == "app_user"
    # Senha com caractere reservado sobrevive a ida e volta.
    assert url.password == "p@ss:w/rd"
    assert url.host == "mysql.railway.internal"
    assert url.database == "assistant"


def test_broken_database_url_without_fallback_is_kept_for_the_driver_error():
    broken = "mysql+aiomysql://:@host:3306/"

    assert resolve_database_url(broken, {}) == broken


def test_sync_mysql_scheme_is_switched_to_the_async_driver():
    """A MYSQL_URL da Railway vem com mysql://, que o engine assincrono recusa."""
    url = resolve_database_url("mysql://root:segredo@host:3306/railway", {})

    assert url == "mysql+aiomysql://root:segredo@host:3306/railway"


def test_railway_template_names_are_accepted():
    env = {"MYSQLUSER": "root", "MYSQLPASSWORD": "x", "MYSQLHOST": "h", "MYSQLDATABASE": "railway"}

    url = make_url(resolve_database_url(DEFAULT, env))

    assert (url.username, url.host, url.database) == ("root", "h", "railway")


def test_underscore_names_win_over_template_names():
    env = {"MYSQL_USER": "compose", "MYSQLUSER": "template", "MYSQL_DATABASE": "db"}

    assert make_url(resolve_database_url(DEFAULT, env)).username == "compose"


def test_partial_variables_keep_the_development_defaults():
    """Comportamento anterior: variavel que falta usa o padrao local."""
    url = make_url(resolve_database_url(DEFAULT, {"MYSQL_HOST": "db"}))

    assert (url.username, url.password, url.host, url.database) == (
        "assistant",
        "assistant",
        "db",
        "assistant",
    )


def test_no_configuration_uses_the_development_default():
    assert resolve_database_url(DEFAULT, {}) == DEFAULT


def test_sqlite_has_no_credentials_to_check():
    assert database_url_problems("sqlite+aiosqlite:///data/app.db") == []
