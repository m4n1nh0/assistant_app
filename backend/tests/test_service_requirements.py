"""Imagens por servico so se pagam se as versoes continuarem batendo.

Cada servico extraido tem o proprio Dockerfile e o proprio arquivo de
requisitos, o que corta gigabytes de imagem - e cria um risco novo: quatro
processos rodando a mesma base de codigo com versoes diferentes de `langchain`
ou de `pydantic`. Esse e o tipo de divergencia que produz bug em um servico e
nao no outro, e que custa um dia para reproduzir.

O `requirements.txt` da assistant-api e a fonte da verdade; os arquivos por
servico sao recortes dele. Estes testes falham quando alguem sobe uma versao la
e esquece aqui - que e exatamente como a deriva comeca.

O que aqui NAO se cobre: pacote que passou a ser necessario e nao foi
acrescentado. Import novo em modulo compartilhado quebra o servico enxuto em
runtime, e quem avisa e o healthcheck do deploy. Era o preco anunciado da
separacao.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parent.parent
BASE = BACKEND / "requirements.txt"
POR_SERVICO = [
    BACKEND / "requirements-mcp-service.txt",
    BACKEND / "requirements-tool-service.txt",
]

# nome[extras]==versao
LINHA = re.compile(r"^([A-Za-z0-9._-]+)(\[[^\]]*\])?==(.+)$")


def _pinos(arquivo: Path) -> dict[str, tuple[str, str]]:
    """Mapa nome normalizado -> (extras, versao) de um arquivo de requisitos."""
    pinos: dict[str, tuple[str, str]] = {}
    for bruta in arquivo.read_text(encoding="utf-8").splitlines():
        linha = bruta.split("#", 1)[0].strip()
        if not linha:
            continue
        casa = LINHA.match(linha)
        assert casa, f"{arquivo.name}: linha sem pino exato: {bruta!r}"
        nome, extras, versao = casa.groups()
        pinos[nome.lower().replace("_", "-")] = (extras or "", versao)
    return pinos


@pytest.fixture(scope="module")
def base() -> dict[str, tuple[str, str]]:
    return _pinos(BASE)


@pytest.mark.parametrize("arquivo", POR_SERVICO, ids=lambda p: p.name)
def test_versoes_batem_com_a_imagem_cheia(arquivo, base):
    """Mesmo pacote, mesma versao e mesmos extras da assistant-api."""
    divergentes = []
    for nome, (extras, versao) in _pinos(arquivo).items():
        if nome not in base:
            continue
        if (extras, versao) != base[nome]:
            divergentes.append(
                f"{nome}: {extras}=={versao} aqui, "
                f"{base[nome][0]}=={base[nome][1]} em requirements.txt"
            )

    assert not divergentes, (
        f"{arquivo.name} divergiu de requirements.txt:\n  "
        + "\n  ".join(divergentes)
    )


@pytest.mark.parametrize("arquivo", POR_SERVICO, ids=lambda p: p.name)
def test_nenhum_pacote_orfao(arquivo, base):
    """Todo pacote do recorte existe no conjunto completo.

    Um pacote que so aparece no arquivo de um servico ou e engano de digitacao,
    ou e dependencia que a assistant-api tambem passou a ter e ninguem
    registrou la.
    """
    orfaos = sorted(set(_pinos(arquivo)) - set(base))

    assert not orfaos, (
        f"{arquivo.name} pina pacote ausente de requirements.txt: "
        f"{', '.join(orfaos)}"
    )


def test_todo_servico_com_dockerfile_tem_requisitos():
    """Dockerfile por servico e arquivo de requisitos andam em par."""
    dockerfiles = sorted(BACKEND.glob("Dockerfile.*"))
    assert dockerfiles, "nenhum Dockerfile por servico encontrado"

    for dockerfile in dockerfiles:
        servico = dockerfile.name.split(".", 1)[1]
        requisitos = BACKEND / f"requirements-{servico}.txt"
        assert requisitos.exists(), (
            f"{dockerfile.name} existe mas {requisitos.name} nao"
        )
        assert requisitos.name in dockerfile.read_text(encoding="utf-8"), (
            f"{dockerfile.name} nao instala {requisitos.name}"
        )
