"""Lista colada com caracteres invisiveis: o nome parece certo e era recusado.

Falha real: ao atualizar a lista da turma de IoT, o cadastro parou em "Linha 7: nome nao
reconhecido: Felipe Figueiredo". O nome estava certo na tela; entre as duas palavras
havia um espaco sem quebra (U+00A0), do WhatsApp, que a regra de nome nao aceitava.
"""

import pytest

from app.services.project_group_service import (
    clean_list_line,
    describe_bad_character,
    parse_project_group_text,
)


def lista(*linhas: str) -> str:
    return "\n".join(linhas)


@pytest.mark.unit
@pytest.mark.parametrize(
    "caractere, descricao",
    [
        (" ", "espaco sem quebra"),
        (" ", "espaco estreito sem quebra"),
        (" ", "espaco largo"),
        ("　", "espaco ideografico"),
    ],
)
def test_espaco_especial_entre_as_palavras_vira_espaco_comum(caractere, descricao):
    grupos, _ = parse_project_group_text(
        lista("Grupo 1", f"Felipe{caractere}Figueiredo", "Nicolas Rosa")
    )

    assert [m["name"] for m in grupos[0]["members"]] == ["Felipe Figueiredo", "Nicolas Rosa"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "marca",
    ["​", "‎", "‏", "‪", "‬", "⁠", "﻿", "­"],
)
def test_marca_invisivel_no_nome_some(marca):
    grupos, _ = parse_project_group_text(
        lista("Grupo 1", f"{marca}Felipe Fi{marca}gueiredo{marca}")
    )

    assert grupos[0]["members"][0]["name"] == "Felipe Figueiredo"


@pytest.mark.unit
def test_marca_de_direcao_antes_do_marcador_da_lista_nao_atrapalha():
    grupos, _ = parse_project_group_text(lista("Grupo 1", "‎- Felipe Figueiredo"))

    assert grupos[0]["members"][0]["name"] == "Felipe Figueiredo"


@pytest.mark.unit
def test_invisivel_no_titulo_do_grupo_e_no_cabecalho():
    grupos, contexto = parse_project_group_text(
        lista("Grupos turma terça IoT:", "Grupo 1", "Ana Souza")
    )

    assert grupos[0]["name"] == "GRUPO 1"
    assert contexto == "Grupos turma terça IoT:"


@pytest.mark.unit
def test_apostrofo_tipografico_vira_apostrofo_comum():
    grupos, _ = parse_project_group_text(lista("Grupo 1", "Joana D’Arc"))

    assert grupos[0]["members"][0]["name"] == "Joana D'Arc"


@pytest.mark.unit
def test_espacos_repetidos_e_nas_pontas_sao_colapsados():
    grupos, _ = parse_project_group_text(
        lista("Grupo 1", "  Felipe    Figueiredo  ")
    )

    assert grupos[0]["members"][0]["name"] == "Felipe Figueiredo"


@pytest.mark.unit
def test_o_mesmo_aluno_com_e_sem_espaco_especial_conta_como_repetido():
    with pytest.raises(ValueError) as erro:
        parse_project_group_text(
            lista("Grupo 1", "Felipe Figueiredo", "Felipe Figueiredo")
        )

    assert "nome repetido" in str(erro.value)


@pytest.mark.unit
def test_nome_realmente_invalido_diz_qual_caractere_atrapalha():
    with pytest.raises(ValueError) as erro:
        parse_project_group_text(lista("Grupo 1", "Felipe @ Figueiredo"))

    mensagem = str(erro.value)
    assert "Linha 2: nome não reconhecido: Felipe @ Figueiredo" in mensagem
    assert "'@' (U+0040)" in mensagem


@pytest.mark.unit
def test_emoji_e_apontado_com_o_codigo():
    with pytest.raises(ValueError) as erro:
        parse_project_group_text(lista("Grupo 1", "Ana Souza \U0001F600"))

    assert "U+1F600" in str(erro.value)


@pytest.mark.unit
def test_descricao_do_caractere_ruim():
    assert "'#' (U+0023)" in describe_bad_character("Ana #1")
    assert describe_bad_character("Ana Souza") == ""
    assert "pelo menos 2" in describe_bad_character("A")


@pytest.mark.unit
def test_limpeza_nao_mexe_em_acentos_nem_hifen():
    assert clean_list_line("  José   da Silva-Santos ") == "José da Silva-Santos"
    # NFD (letra + acento solto) volta composto, como o cadastro guarda.
    assert clean_list_line("José Lima") == "José Lima"


@pytest.mark.unit
def test_marcador_v_de_presente_continua_sendo_lido():
    grupos, _ = parse_project_group_text(lista("Grupo 1", "Joao Vitor Pereira v"))

    membro = grupos[0]["members"][0]
    assert membro["name"] == "Joao Vitor Pereira" and membro["note"] == "v"
