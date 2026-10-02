"""Recorte de texto longo que cobre o documento inteiro, nao so o comeco.

Um PDF de 43 paginas nao cabe no contexto do modelo; alguma coisa tem de ficar de
fora. Pegar so o comeco deixava o fim do material - a segunda metade do conteudo -
sem nenhuma pergunta, e piorava a cada vez que a fonte precisava encolher: dividida
entre varias aulas, ou reduzida para caber num provedor menor, so as primeiras
paginas sobravam.

Aqui o recorte sai de trechos espacados do comeco ao fim, cada um cortado em fim
de paragrafo ou de frase, separados por uma marca de omissao para o modelo saber
que ha texto entre eles.
"""

from __future__ import annotations

import math

#: Tamanho que cada trecho busca ter. Menor que isso o trecho nao carrega uma ideia
#: inteira; maior reduz a quantidade de pontos do documento que entram.
TARGET_CHUNK_CHARS = 5_000

MIN_CHUNKS = 3
MAX_CHUNKS = 10

#: Marca entre dois trechos: diz ao modelo que o texto continua em outro ponto, para
#: ele nao tratar o fim de um trecho e o comeco do seguinte como uma frase so.
OMISSION = "\n\n[… trecho omitido …]\n\n"


def _cut(text: str, start: int, size: int) -> str:
    """Um trecho de ate `size` caracteres, comecando e terminando em fronteira."""
    if start > 0:
        # Comeca no proximo paragrafo, para nao abrir no meio de uma frase.
        janela = text[start:start + max(size // 6, 200)]
        salto = janela.find("\n\n")
        if salto >= 0:
            start += salto + 2

    pedaco = text[start:start + size]
    if start + size >= len(text):
        return pedaco.strip()

    for marca in ("\n\n", ". ", "\n", " "):
        posicao = pedaco.rfind(marca)
        if posicao >= size // 2:
            return pedaco[: posicao + (1 if marca == ". " else 0)].strip()
    return pedaco.strip()


def sample_evenly(text: str, limit: int) -> str:
    """Recorte de ate `limit` caracteres que cobre o texto do comeco ao fim.

    Texto que cabe volta inteiro. Senao, sai de `n` trechos espacados por igual
    (o primeiro no comeco e o ultimo terminando no fim do documento), com a
    omissao entre eles contada no limite.
    """
    if len(text) <= limit:
        return text

    chunks = min(max(math.ceil(limit / TARGET_CHUNK_CHARS), MIN_CHUNKS), MAX_CHUNKS)
    size = (limit - (chunks - 1) * len(OMISSION)) // chunks
    if size < 200:
        # Limite minusculo: nao ha espaco para varios trechos, vale o comeco.
        return _cut(text, 0, limit)

    ultimo_inicio = len(text) - size
    pedacos = [
        _cut(text, round(i * ultimo_inicio / (chunks - 1)), size)
        for i in range(chunks)
    ]
    return OMISSION.join(pedaco for pedaco in pedacos if pedaco)
