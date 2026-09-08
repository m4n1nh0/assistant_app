"""OCR do material: ordem de leitura, confianca e degradacao sem o pacote.

O que decide a qualidade do texto que chega ao gerador de quiz nao e o modelo -
e o que se faz com a saida dele. O detector devolve caixas na ordem em que as
encontrou, e uma linha mal reconhecida vale menos que linha nenhuma. As duas
coisas se resolvem aqui, e sao testaveis sem carregar modelo algum.
"""

from __future__ import annotations

import pytest

from app.services import ocr_service as ocr


class _Saida:
    """Imita o retorno do RapidOCR: caixas, textos e confiancas em paralelo."""

    def __init__(self, itens: list[tuple[str, float, float, float]]):
        # Cada item e (texto, topo, esquerda, confianca).
        self.boxes = [
            [
                [esquerda, topo],
                [esquerda + 220, topo],
                [esquerda + 220, topo + 30],
                [esquerda, topo + 30],
            ]
            for _, topo, esquerda, _ in itens
        ]
        self.txts = tuple(texto for texto, _, _, _ in itens)
        self.scores = tuple(score for _, _, _, score in itens)


# --- Ordem de leitura --------------------------------------------------------


def test_linhas_saem_na_ordem_de_leitura_e_nao_na_de_deteccao():
    # O detector achou o rodape primeiro; publicar nessa ordem entregaria ao
    # gerador de quiz um texto embaralhado.
    saida = _Saida(
        [
            ("Pagina 12", 900.0, 60.0, 0.95),
            ("Normalizacao de dados", 100.0, 60.0, 0.98),
            ("A terceira forma normal", 200.0, 60.0, 0.97),
        ]
    )

    assert ocr._ordered_lines(saida) == [
        "Normalizacao de dados",
        "A terceira forma normal",
        "Pagina 12",
    ]


def test_colunas_da_mesma_linha_saem_da_esquerda_para_a_direita():
    # Duas caixas na mesma altura: e a horizontal que decide.
    saida = _Saida(
        [
            ("segunda coluna", 300.0, 700.0, 0.95),
            ("primeira coluna", 302.0, 60.0, 0.95),
        ]
    )

    assert ocr._ordered_lines(saida) == ["primeira coluna", "segunda coluna"]


def test_pequena_diferenca_de_altura_nao_quebra_a_mesma_linha():
    """Letras da mesma linha quase nunca caem no mesmo pixel.

    Sem a tolerancia tirada da altura das caixas, a segunda metade da linha
    viraria uma linha propria e o texto sairia picado.
    """
    saida = _Saida(
        [
            ("continua aqui", 104.0, 640.0, 0.95),
            ("A frase comeca", 100.0, 60.0, 0.95),
            ("linha de baixo", 400.0, 60.0, 0.95),
        ]
    )

    assert ocr._ordered_lines(saida) == [
        "A frase comeca",
        "continua aqui",
        "linha de baixo",
    ]


# --- Confianca ---------------------------------------------------------------


def test_linha_mal_reconhecida_e_descartada(monkeypatch):
    # Texto errado e pior que texto faltando: o gerador de quiz nao tem como
    # desconfiar dele e produziria pergunta sobre um conceito inexistente.
    monkeypatch.setattr(ocr.settings, "ocr_min_score", 0.5, raising=False)
    saida = _Saida(
        [
            ("conceito legivel", 100.0, 60.0, 0.93),
            ("rnn9 ~~ ilegivel", 200.0, 60.0, 0.12),
        ]
    )

    assert ocr._ordered_lines(saida) == ["conceito legivel"]


def test_pagina_sem_nada_reconhecivel_devolve_lista_vazia():
    assert ocr._ordered_lines(_Saida([])) == []


def test_caixa_so_com_espaco_nao_vira_linha():
    saida = _Saida([("   ", 100.0, 60.0, 0.99)])

    assert ocr._ordered_lines(saida) == []


# --- Disponibilidade ---------------------------------------------------------


def test_ocr_desligado_na_configuracao_nao_e_tentado(monkeypatch):
    monkeypatch.setattr(ocr.settings, "ocr_enabled", False, raising=False)

    assert ocr.is_available() is False


def test_falha_de_carga_nao_e_repetida_a_cada_upload(monkeypatch):
    # Sem essa marca, todo material recaia no mesmo erro de import, pagando o
    # custo da tentativa de novo.
    monkeypatch.setattr(ocr.settings, "ocr_enabled", True, raising=False)
    monkeypatch.setattr(ocr, "_load_failed", True)

    assert ocr.is_available() is False


def test_imagem_ilegivel_nao_estoura_excecao_crua():
    # Arquivo corrompido devolve vazio, e quem chama transforma em MaterialError
    # com um motivo que o professor entende.
    assert ocr.text_from_image(b"isto nao e uma imagem") == ""


@pytest.mark.parametrize("extensao", [".jpg", ".png", ".webp"])
def test_formatos_de_foto_comuns_estao_previstos(extensao):
    assert extensao in ocr.IMAGE_EXTENSIONS
