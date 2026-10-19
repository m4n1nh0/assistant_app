"""Divide um texto pronto em pedacos, para entregar no formato de streaming.

O chat inteiro passa pelo grafo (orquestrador), que devolve a resposta completa. Os
endpoints de streaming mantem o contrato de pedacos que a interface conhece, mas cada
pedaco sai desta divisao e nao de um token do provedor.
"""

from __future__ import annotations

import re
from typing import Iterator

_WORD = re.compile(r"\S+\s*|\s+")


def text_chunks(text: str, size: int = 48) -> Iterator[str]:
    """Pedacos de ate ~`size` caracteres, sempre cortando entre palavras.

    Juntar os pedacos devolve exatamente o texto original, com espacos e quebras de linha.
    Uma palavra maior que `size` fica inteira no seu pedaco.
    """
    current = ""
    for token in _WORD.findall(text or ""):
        if current and len(current) + len(token) > size:
            yield current
            current = ""
        current += token
    if current:
        yield current
