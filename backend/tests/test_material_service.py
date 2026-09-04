"""Leitura de material didatico: limpeza, corte e erro honesto.

O gerador de quiz recebe esse texto no prompt. Texto picado por quebra de linha
de PDF produz pergunta sobre fragmento; texto grande demais volta cortado do
modelo e derruba o quiz no gerador por template. As duas coisas se resolvem
aqui, antes de chegar na IA.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import material_service as ms


class _Page:
    def __init__(self, text: str = "", erro: Exception | None = None):
        self._text = text
        self._erro = erro

    def extract_text(self) -> str:
        if self._erro:
            raise self._erro
        return self._text


def _texto_longo(prefixo: str = "") -> str:
    return prefixo + " ".join(
        f"A juncao interna retorna somente as linhas que atendem a condicao {i}."
        for i in range(1, 12)
    )


# --- Limpeza ----------------------------------------------------------------


def test_junta_linha_quebrada_pela_largura_da_pagina():
    # PDF quebra por largura, nao por sentido: sem juntar, o modelo recebe meio
    # conceito por linha.
    limpo = ms.clean_text("A juncao de tabelas e uma\ndas operacoes do modelo\nrelacional.")

    assert limpo == "A juncao de tabelas e uma das operacoes do modelo relacional."


def test_junta_palavra_hifenizada_no_fim_da_linha():
    limpo = ms.clean_text("O produto carte-\nsiano combina tudo.")

    assert "cartesiano" in limpo


def test_preserva_a_divisao_entre_paragrafos():
    # E ela que separa um assunto do proximo; achatar tudo viraria um bloco so.
    limpo = ms.clean_text("Primeiro assunto\ncontinua aqui.\n\nSegundo assunto.")

    assert limpo == "Primeiro assunto continua aqui.\n\nSegundo assunto."


# --- Extracao ---------------------------------------------------------------


def test_pagina_ilegivel_nao_perde_o_material_inteiro():
    paginas = [
        _Page(_texto_longo("Pagina boa. ")),
        _Page(erro=ValueError("fonte corrompida")),
        _Page(_texto_longo("Outra pagina boa. ")),
    ]

    extraido = ms.from_pages(paginas)

    assert extraido.page_count == 2
    assert "Pagina boa" in extraido.text
    assert "Outra pagina boa" in extraido.text


def test_pdf_digitalizado_falha_com_motivo():
    # PDF de imagem extrai vazio. Gravar material em branco daria erro so la na
    # frente, na geracao do quiz, sem explicar a causa.
    with pytest.raises(ms.MaterialError, match="OCR"):
        ms.from_pages([_Page(""), _Page("   ")])


def test_material_grande_e_cortado_e_avisa(monkeypatch):
    monkeypatch.setattr(ms, "MAX_CHARS", 400)

    extraido = ms.from_pages([_Page(_texto_longo()), _Page(_texto_longo())])

    assert extraido.truncated is True
    assert extraido.char_count <= 400


def test_arquivo_vazio_nao_vira_material():
    with pytest.raises(ms.MaterialError):
        asyncio.run(ms.extract_pdf(b""))


def test_pdf_ilegivel_falha_sem_estourar_excecao_crua():
    with pytest.raises(ms.MaterialError, match="Nao consegui ler"):
        asyncio.run(ms.extract_pdf(b"isto nao e um PDF"))


# --- Recorte para o quiz ----------------------------------------------------


def test_recorte_para_o_quiz_termina_em_paragrafo():
    texto = "\n\n".join(_texto_longo(f"Bloco {i}. ") for i in range(1, 8))

    recorte = ms.summary_for_quiz(texto, limit=1200)

    assert len(recorte) <= 1200
    # Corte no meio de uma frase entregaria contexto truncado ao modelo.
    assert not recorte.endswith(("condicao", "a", "de"))


def test_material_pequeno_vai_inteiro():
    texto = "Material curto sobre juncoes."

    assert ms.summary_for_quiz(texto) == texto


# --- Vinculo com a disciplina ------------------------------------------------


class _FakeDisciplineDb:
    """Banco minimo com as disciplinas do professor."""

    def __init__(self, disciplinas):
        self._disciplinas = disciplinas

    async def get(self, _model, item_id):
        return next((d for d in self._disciplinas if d.id == item_id), None)

    async def execute(self, _query):
        disciplinas = self._disciplinas

        class _R:
            def scalars(self):
                class _S:
                    def all(self_inner):
                        return disciplinas

                return _S()

        return _R()


def _disciplina(id_, code, name, tutor="tutor-1"):
    from types import SimpleNamespace

    return SimpleNamespace(id=id_, code=code, name=name, tutor_id=tutor)


def test_material_por_texto_encontra_a_disciplina_cadastrada():
    """Texto que casa com o cadastro ganha o vinculo: sem o id, renomear a
    disciplina soltaria o material dela."""
    from app.routers.education import _resolve_discipline

    db = _FakeDisciplineDb([_disciplina("d1", "ARA0040", "BANCO DE DADOS")])

    vinculo, rotulo = asyncio.run(
        _resolve_discipline("", "ARA0040 - BANCO DE DADOS", "tutor-1", db)
    )

    assert vinculo == "d1"
    assert rotulo == "ARA0040 - BANCO DE DADOS"


def test_material_de_disciplina_nao_cadastrada_ainda_sobe():
    # Travar o upload obrigaria a cadastrar a disciplina antes; o material vale
    # por si, e o vinculo pode vir depois.
    from app.routers.education import _resolve_discipline

    db = _FakeDisciplineDb([])

    vinculo, rotulo = asyncio.run(
        _resolve_discipline("", "Materia nova", "tutor-1", db)
    )

    assert vinculo is None
    assert rotulo == "Materia nova"


def test_disciplina_de_outro_professor_e_recusada():
    from fastapi import HTTPException

    from app.routers.education import _resolve_discipline

    db = _FakeDisciplineDb([_disciplina("d1", "ARA0040", "BD", tutor="outro")])

    with pytest.raises(HTTPException) as erro:
        asyncio.run(_resolve_discipline("d1", "", "tutor-1", db))

    assert erro.value.status_code == 404
