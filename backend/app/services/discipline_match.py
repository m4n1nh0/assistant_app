"""Comparacao de nome de disciplina que perdoa a grafia.

Aula, material e quiz guardam a disciplina como **texto**, e cada um nasce de um
lugar diferente: a aula leva o que foi digitado ao gravar ("ARA0040-BANCO DE
DADOS"); o material importado pelo seletor do app leva o rotulo da disciplina
cadastrada ("ARA0040 - BANCO DE DADOS"). Comparar os dois por igualdade exata
fazia o PDF importado nunca aparecer como fonte do quiz daquela aula - sem erro
nenhum, so a lista sem o material.

Aula nao tem vinculo com a disciplina cadastrada (so o texto), entao e a
comparacao que precisa ser tolerante.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

#: Codigo de curso no padrao das instituicoes: tres a cinco letras e tres a cinco
#: digitos ("ARA0040", "ENG 101"). E o que identifica a disciplina mesmo quando o
#: nome foi escrito de outro jeito.
_CODE = re.compile(r"\b([a-z]{3,5})\s*-?\s*(\d{3,5})\b")


def _fold(text: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", text or "")
    sem_acento = "".join(ch for ch in sem_acento if not unicodedata.combining(ch))
    return sem_acento.casefold()


def discipline_key(text: Optional[str]) -> str:
    """Chave de comparacao: sem acento, sem caixa, so letras e numeros.

    "ARA0040-BANCO DE DADOS" e "ARA0040 - Banco de Dados" dao a mesma chave.
    """
    return re.sub(r"[^a-z0-9]+", "", _fold(text or ""))


def discipline_code(text: Optional[str]) -> str:
    """Codigo do curso no texto ("ara0040"), ou vazio quando nao ha."""
    achado = _CODE.search(_fold(text or ""))
    return f"{achado.group(1)}{achado.group(2)}" if achado else ""


def same_discipline(first: Optional[str], second: Optional[str]) -> bool:
    """Diz se dois textos nomeiam a mesma disciplina.

    Iguais pela chave, ou com o mesmo codigo de curso (o nome pode ter sido
    abreviado ou reescrito, o codigo nao). Texto vazio nunca casa com nada: uma
    aula sem disciplina nao pode "ser da mesma" que um material sem disciplina.
    """
    key_a, key_b = discipline_key(first), discipline_key(second)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    code_a, code_b = discipline_code(first), discipline_code(second)
    return bool(code_a) and code_a == code_b
