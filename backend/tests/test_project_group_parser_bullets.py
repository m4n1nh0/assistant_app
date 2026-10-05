"""A lista de grupos como chega do chat: nomes com marcador de lista ("- Nome").

Falha real: a lista da turma da segunda, colada com "- Kaic Vinicius" em cada linha,
era recusada com "Linha 3: nome nao reconhecido", porque o nome precisava comecar
por letra.
"""

import pytest

from app.services.project_group_service import parse_project_group_text

LISTA_REAL = """Grupos turma segunda:
GRUPO 1
- Kaic Vinicius
- Kauan Martins
- Antônio

GRUPO 2
- Igor Alan

GRUPO 3
- Lucas Motta
- Salomão
- Lucas Pedral
- João Vitor Andrade

GRUPO 4
- Luiz Fernando

GRUPO 5
- João Vitor Silva
- Marcos Lima

GRUPO 6
- Tiago Tojal

GRUPO 7
- Cauã Vinicius

GRUPO 8
- Davi Leite
- Daniel Santos Lima
- Jonas Natanael
- Guilherme Wilton
- Luiz Ricardo

GRUPO 9
- João Cláudio Menezes
- Wilson Brito Santos
- Daniel Viana
- Felipe Emanoel
- Silas Daniel
- Albert Cruz

GRUPO 10
- Marcella Matos
- Natanael Alves
- David Lima
- Alan Felipe
- Murilo Santos
- Vitor Rafael
- Julio Gabriel
"""


@pytest.mark.unit
def test_a_lista_da_turma_da_segunda_e_aceita_inteira():
    grupos, contexto = parse_project_group_text(LISTA_REAL)

    assert [g["name"] for g in grupos] == [f"GRUPO {n}" for n in range(1, 11)]
    assert [len(g["members"]) for g in grupos] == [3, 1, 4, 1, 2, 1, 1, 5, 6, 7]
    assert sum(len(g["members"]) for g in grupos) == 31
    # O titulo da lista nao vira grupo nem integrante: fica como contexto.
    assert contexto == "Grupos turma segunda:"


@pytest.mark.unit
def test_o_marcador_nao_entra_no_nome_e_os_acentos_ficam():
    grupos, _ = parse_project_group_text(LISTA_REAL)

    assert grupos[0]["members"][2]["name"] == "Antônio"
    assert grupos[2]["members"][3]["name"] == "João Vitor Andrade"
    assert grupos[8]["members"][0]["name"] == "João Cláudio Menezes"
    assert all(not m["name"].startswith("-") for g in grupos for m in g["members"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "linha",
    ["- Ana Souza", "– Ana Souza", "— Ana Souza", "• Ana Souza", "* Ana Souza",
     "1. Ana Souza", "2) Ana Souza", "  -   Ana Souza  ", "Ana Souza"],
)
def test_cada_marcador_de_lista_comum_e_aceito(linha):
    grupos, _ = parse_project_group_text(f"GRUPO 1\n{linha}\n")
    assert grupos[0]["members"] == [{"name": "Ana Souza", "note": ""}]


@pytest.mark.unit
def test_hifen_dentro_do_nome_e_preservado():
    grupos, _ = parse_project_group_text("GRUPO 1\n- Ana-Maria Souza\nMaria-Clara Lima\n")
    assert [m["name"] for m in grupos[0]["members"]] == ["Ana-Maria Souza", "Maria-Clara Lima"]


@pytest.mark.unit
def test_marcacao_de_presenca_continua_valendo_com_o_marcador():
    grupos, _ = parse_project_group_text("GRUPO 1\n- Ana Souza v\n- Bia Lima\n")
    assert grupos[0]["members"] == [
        {"name": "Ana Souza", "note": "v"},
        {"name": "Bia Lima", "note": ""},
    ]


@pytest.mark.unit
def test_linha_so_com_o_marcador_continua_sendo_erro():
    with pytest.raises(ValueError, match="nome não reconhecido"):
        parse_project_group_text("GRUPO 1\n- Ana Souza\n-\n")


@pytest.mark.unit
def test_nome_repetido_no_grupo_e_detectado_mesmo_com_marcadores_diferentes():
    with pytest.raises(ValueError, match="nome repetido"):
        parse_project_group_text("GRUPO 1\n- Ana Souza\n* ana souza\n")
