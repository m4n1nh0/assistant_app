"""Leitura de material didatico enviado pelo professor.

Aula gravada nem sempre e a melhor fonte de quiz: o material da disciplina -
apostila, slide, capitulo - ja vem organizado por topico e escrito com rigor. O
que este modulo faz e transformar esse arquivo em texto aproveitavel pelo mesmo
gerador de quiz que hoje le o resumo da aula.

A extracao roda em thread separada (`asyncio.to_thread`). Ler um PDF de dezenas
de paginas e trabalho de CPU: no event loop, ele congelaria todas as outras
requisicoes do servidor durante o upload.
"""

from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

#: Teto por material. Acima disso o texto e cortado: o gerador de quiz manda
#: tudo para o modelo, e material inteiro estoura a janela de contexto.
MAX_CHARS = 120_000

#: Abaixo disso nao ha material aproveitavel - tipicamente PDF escaneado, que e
#: imagem e precisaria de OCR.
MIN_CHARS = 200


class MaterialError(ValueError):
    """Arquivo que nao da para aproveitar como material."""


@dataclass(frozen=True)
class ExtractedMaterial:
    """Texto extraido de um arquivo, com o que veio dele."""

    text: str
    page_count: int
    truncated: bool

    @property
    def char_count(self) -> int:
        return len(self.text)


async def extract_pdf(data: bytes) -> ExtractedMaterial:
    """Extrai o texto de um PDF sem segurar o event loop.

    Raises:
        MaterialError: arquivo ilegivel, vazio ou sem texto extraivel.
    """
    if not data:
        raise MaterialError("Arquivo vazio.")
    return await asyncio.to_thread(extract_pdf_sync, data)


def extract_pdf_sync(data: bytes) -> ExtractedMaterial:
    """A extracao propriamente dita. Sincrona de proposito, para rodar em thread."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise MaterialError(f"Nao consegui ler o PDF: {exc}") from exc

    return from_pages(reader.pages)


def from_pages(pages: Any) -> ExtractedMaterial:
    """Junta as paginas em texto limpo.

    Separado da leitura do arquivo para o teste exercitar a limpeza, o corte e a
    pagina defeituosa sem precisar montar um PDF de verdade.

    Raises:
        MaterialError: quando sobra texto de menos para virar material.
    """
    parts: list[str] = []
    for index, page in enumerate(pages):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:
            # Uma pagina quebrada nao pode perder o material inteiro.
            logger.warning(f"Pagina {index + 1} do material ilegivel: {exc}")
            continue
        cleaned = clean_text(raw)
        if cleaned:
            parts.append(cleaned)

    text = "\n\n".join(parts).strip()
    if len(text) < MIN_CHARS:
        raise MaterialError(
            "O arquivo nao tem texto extraivel. Se for um PDF digitalizado, "
            "ele e imagem e precisaria de OCR."
        )

    return ExtractedMaterial(
        text=text[:MAX_CHARS].strip(),
        page_count=len(parts),
        truncated=len(text) > MAX_CHARS,
    )


def clean_text(raw: str) -> str:
    """Tira o ruido tipico de PDF que atrapalha o modelo.

    PDF quebra linha por largura de pagina, nao por sentido: o texto chega
    picado no meio das frases e com palavras hifenizadas. Sem juntar, o gerador
    recebe meio conceito por linha e produz pergunta sobre fragmento.

    A divisao entre paragrafos e preservada - e ela que separa um assunto do
    proximo -, entao a limpeza acontece paragrafo a paragrafo, e nao sobre o
    texto inteiro.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Palavra hifenizada quebrada entre linhas: "junc-\nao" -> "juncao".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    paragrafos = []
    for bloco in re.split(r"\n\s*\n", text):
        junto = re.sub(r"\s*\n\s*", " ", bloco)
        junto = re.sub(r"[ \t]{2,}", " ", junto).strip()
        if junto:
            paragrafos.append(junto)
    return "\n\n".join(paragrafos)


def summary_for_quiz(text: str, *, limit: int = 24_000) -> str:
    """Recorte do material que vai como contexto para gerar o quiz.

    O gerador manda o texto inteiro no prompt. Material grande estoura a janela
    do modelo e volta cortado - o mesmo defeito que fazia o quiz cair no gerador
    por template -, entao aqui ele para no fim de um paragrafo.
    """
    if len(text) <= limit:
        return text
    corte = text[:limit]
    ultimo = corte.rfind("\n\n")
    if ultimo > limit // 2:
        corte = corte[:ultimo]
    return corte.strip()
