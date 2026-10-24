"""Cofre de segredos: o ENTRYPOINT busca no Infisical e falha fechado; o servico exige a marca.

O `infisical` real nao roda aqui: um falso no PATH registra como foi chamado e executa o comando
depois do `--`, como o CLI faz. O que se prova e o contrato do script, nao a rede.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from shared.settings import ServiceSettings

SCRIPT = Path(__file__).resolve().parent.parent / "docker" / "infisical-entrypoint.sh"
pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="precisa de sh")

FAKE = textwrap.dedent("""\
    #!/bin/sh
    echo "$@" >> "$FAKE_LOG"
    case "$1" in
      login) [ "${FAKE_LOGIN_EXIT:-0}" = 0 ] && echo faketoken; exit "${FAKE_LOGIN_EXIT:-0}" ;;
      run) shift; while [ "$1" != "--" ]; do shift; done; shift; exec "$@" ;;
    esac
""")


@pytest.fixture
def box(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "infisical").write_text(FAKE)
    (fake / "infisical").chmod(0o755)
    log = tmp_path / "calls.log"

    def run(env=None, command=("sh", "-c", 'echo "OUT token=${INFISICAL_TOKEN:-} secret=${INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET:-} injected=${INFISICAL_INJECTED:-}"')):
        base = {"PATH": f"{fake}:{os.environ['PATH']}", "FAKE_LOG": str(log),
                "INFISICAL_LOGIN_RETRY_DELAY": "0"}
        result = subprocess.run(["sh", str(SCRIPT), *command], env={**base, **(env or {})},
                                capture_output=True, text=True, timeout=30)
        calls = log.read_text().splitlines() if log.exists() else []
        return result, calls

    return run


FULL = {"INFISICAL_PROJECT_ID": "proj-1", "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID": "cid",
        "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET": "csecret"}


def test_sem_cofre_configurado_roda_o_comando_direto(box):
    result, calls = box(command=("echo", "oi"))

    assert result.returncode == 0 and result.stdout.strip() == "oi"
    assert calls == []  # nem tentou falar com o cofre


def test_com_cofre_busca_o_token_e_sobe_o_comando_com_os_segredos(box):
    result, calls = box({**FULL, "INFISICAL_SECRET_PATH": "/orchestrator"})

    assert result.returncode == 0
    assert calls[0] == "login --method=universal-auth --plain --silent"
    assert "run --silent --projectId proj-1 --env prod --path /orchestrator --" in calls[1]
    # o processo recebe o token e a marca, mas nao o secret de login (e ele nunca vai no argv)
    assert "token=faketoken" in result.stdout and "injected=1" in result.stdout
    assert "secret= " in result.stdout
    assert "csecret" not in "".join(calls)


def test_padroes_sao_ambiente_prod_e_pasta_raiz(box):
    _, calls = box(FULL)

    assert "--env prod --path /" in calls[1]


def test_token_ja_emitido_dispensa_o_login(box):
    result, calls = box({"INFISICAL_PROJECT_ID": "proj-1", "INFISICAL_TOKEN": "pronto"})

    assert result.returncode == 0 and "token=pronto" in result.stdout
    assert [c.split()[0] for c in calls] == ["run"]


@pytest.mark.parametrize("faltando", ["INFISICAL_PROJECT_ID", "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID",
                                      "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET"])
def test_configuracao_incompleta_nao_sobe_nem_cai_para_o_modo_sem_cofre(box, faltando):
    env = {k: v for k, v in FULL.items() if k != faltando}

    result, calls = box(env, command=("echo", "NAO_DEVIA_SUBIR"))

    assert result.returncode == 78 and "NAO_DEVIA_SUBIR" not in result.stdout
    assert faltando in result.stderr


def test_login_recusado_falha_fechado_depois_de_tres_tentativas(box):
    result, calls = box({**FULL, "FAKE_LOGIN_EXIT": "1"}, command=("echo", "NAO_DEVIA_SUBIR"))

    assert result.returncode == 78 and "NAO_DEVIA_SUBIR" not in result.stdout
    assert [c.split()[0] for c in calls] == ["login", "login", "login"]


def test_sem_o_cli_na_imagem_nao_sobe(tmp_path):
    result = subprocess.run(
        ["sh", str(SCRIPT), "echo", "x"], capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", **FULL})

    assert result.returncode == 78 and "CLI do Infisical" in result.stderr


# --- a trava no servico ------------------------------------------------------------------------


def test_servico_com_cofre_obrigatorio_recusa_subir_sem_a_marca(monkeypatch):
    monkeypatch.setenv("INFISICAL_REQUIRED", "true")
    monkeypatch.delenv("INFISICAL_INJECTED", raising=False)

    with pytest.raises(RuntimeError, match="infisical-entrypoint"):
        ServiceSettings(_env_file=None)


def test_servico_sobe_com_a_marca_ou_sem_exigir_o_cofre(monkeypatch):
    monkeypatch.setenv("INFISICAL_REQUIRED", "true")
    monkeypatch.setenv("INFISICAL_INJECTED", "1")
    assert ServiceSettings(_env_file=None).infisical_required is True

    monkeypatch.delenv("INFISICAL_REQUIRED")
    monkeypatch.delenv("INFISICAL_INJECTED")
    assert ServiceSettings(_env_file=None).infisical_required is False
