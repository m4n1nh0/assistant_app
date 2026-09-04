"""O commit que esta rodando, exposto pela API.

Existe por um episodio concreto: a importacao de alunos parou de desativar, e a
causa era producao rodando um commit anterior. Descobrir isso exigiu comparar o
formato do `openapi.json` com o codigo local - com o commit no `/health`, e um
`curl`.
"""

from __future__ import annotations

import pytest

from app.core.config import build_revision


@pytest.fixture(autouse=True)
def sem_variaveis_de_deploy(monkeypatch):
    for name in (
        "RAILWAY_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT",
        "SOURCE_COMMIT",
        "GIT_COMMIT_SHA",
    ):
        monkeypatch.delenv(name, raising=False)


def test_sem_ambiente_de_deploy_a_revisao_fica_vazia():
    # Em desenvolvimento nao ha commit publicado: vazio e a resposta honesta,
    # melhor que inventar "dev" e alguem confundir com uma versao real.
    assert build_revision() == ""


def test_usa_o_sha_curto_do_provedor(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "d568060a1b2c3d4e5f6")

    assert build_revision() == "d568060"


@pytest.mark.parametrize(
    "variavel",
    ["RENDER_GIT_COMMIT", "SOURCE_COMMIT", "GIT_COMMIT_SHA"],
)
def test_reconhece_outros_provedores(monkeypatch, variavel):
    monkeypatch.setenv(variavel, "abc1234def")

    assert build_revision() == "abc1234"


def test_variavel_vazia_nao_vira_revisao(monkeypatch):
    # Provedor que define a variavel sem valor nao pode virar revisao em branco
    # com aparencia de resposta.
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "   ")
    monkeypatch.setenv("SOURCE_COMMIT", "abc1234def")

    assert build_revision() == "abc1234"
