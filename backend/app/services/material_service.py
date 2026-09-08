"""Leitura de material didatico enviado pelo professor.

Aula gravada nem sempre e a melhor fonte de quiz: o material da disciplina -
apostila, slide, capitulo - ja vem organizado por topico e escrito com rigor. O
que este modulo faz e transformar esse arquivo em texto aproveitavel pelo mesmo
gerador de quiz que hoje le o resumo da aula.

Cada formato entra por um extrator proprio e sai como uma sequencia de blocos de
texto; dai para frente o caminho e um so (`from_blocks`): limpeza, juncao, teto
e piso. Adicionar um formato e escrever o extrator e registra-lo em
`_EXTRACTORS` - nada mais no modulo precisa saber que ele existe.

O que chega como imagem - apostila digitalizada, foto do quadro - passa antes
pelo `ocr_service`. O OCR e opcional: se estiver desligado ou nao instalado, o
arquivo volta a ser recusado com o motivo de sempre, e nenhum outro formato
deixa de funcionar por causa disso.

A extracao roda em thread separada (`asyncio.to_thread`). Ler um PDF de dezenas
de paginas e trabalho de CPU: no event loop, ele congelaria todas as outras
requisicoes do servidor durante o upload.
"""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from loguru import logger

from . import ocr_service

#: Teto por material. Acima disso o texto e cortado: o gerador de quiz manda
#: tudo para o modelo, e material inteiro estoura a janela de contexto.
MAX_CHARS = 120_000

#: Abaixo disso nao ha material aproveitavel.
MIN_CHARS = 200

#: Motivo para os formatos que podem chegar como imagem. PDF escaneado extrai
#: vazio, e sem essa explicacao o professor so ve "material em branco".
SCANNED_HINT = (
    "O arquivo nao tem texto extraivel. Se for um PDF digitalizado, "
    "ele e imagem e precisaria de OCR."
)

#: Motivo para os formatos que sempre carregam texto. Aqui vazio e vazio mesmo:
#: falar de OCR num .docx so confundiria.
EMPTY_HINT = "O arquivo nao tem texto suficiente para virar material."


class MaterialError(ValueError):
    """Arquivo que nao da para aproveitar como material."""


@dataclass(frozen=True)
class ExtractedMaterial:
    """Texto extraido de um arquivo, com o que veio dele."""

    text: str
    page_count: int
    truncated: bool
    #: De que formato o texto saiu. Vai para o banco e permite a interface
    #: dizer "12 slides" em vez de "12 paginas".
    source_type: str = "pdf"

    @property
    def char_count(self) -> int:
        return len(self.text)


# --- Caminho comum a todos os formatos --------------------------------------


def from_blocks(
    blocks: Iterable[str],
    *,
    source_type: str,
    rewrap: bool = True,
    empty_hint: str = EMPTY_HINT,
) -> ExtractedMaterial:
    """Junta os blocos de um material em texto limpo.

    Bloco e a unidade natural do formato: pagina no PDF, slide no PPTX, o
    documento inteiro no DOCX - que nao tem pagina antes de ser renderizado.
    E por isso que `page_count` conta blocos, e nao paragrafos.

    Raises:
        MaterialError: quando sobra texto de menos para virar material.
    """
    parts: list[str] = []
    for raw in blocks:
        cleaned = clean_text(raw, rewrap=rewrap)
        if cleaned:
            parts.append(cleaned)

    text = "\n\n".join(parts).strip()
    if len(text) < MIN_CHARS:
        raise MaterialError(empty_hint)

    return ExtractedMaterial(
        text=text[:MAX_CHARS].strip(),
        page_count=len(parts),
        truncated=len(text) > MAX_CHARS,
        source_type=source_type,
    )


def clean_text(raw: str, *, rewrap: bool = True) -> str:
    """Tira o ruido tipico do arquivo que atrapalha o modelo.

    PDF quebra linha por largura de pagina, nao por sentido: o texto chega
    picado no meio das frases e com palavras hifenizadas. Sem juntar, o gerador
    recebe meio conceito por linha e produz pergunta sobre fragmento. E isso que
    `rewrap` faz.

    Em DOCX, PPTX e Markdown a quebra de linha ja tem sentido - e um bullet de
    slide, um item de lista -, e juntar acharia o slide inteiro num paragrafo
    corrido. Nesses formatos o chamador passa `rewrap=False`.

    A divisao entre paragrafos e preservada nos dois casos - e ela que separa um
    assunto do proximo -, entao a limpeza acontece paragrafo a paragrafo, e nao
    sobre o texto inteiro.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if rewrap:
        # Palavra hifenizada quebrada entre linhas: "junc-\nao" -> "juncao".
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    paragrafos = []
    for bloco in re.split(r"\n\s*\n", text):
        if rewrap:
            junto = re.sub(r"\s*\n\s*", " ", bloco)
        else:
            junto = "\n".join(
                linha.strip() for linha in bloco.split("\n") if linha.strip()
            )
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


# --- PDF ---------------------------------------------------------------------


def extract_pdf_sync(data: bytes) -> ExtractedMaterial:
    """A extracao propriamente dita. Sincrona de proposito, para rodar em thread.

    PDF digitalizado nao tem camada de texto e sai vazio da leitura normal. Em
    vez de recusar o arquivo, cai para o OCR - e so volta a recusar, com a
    mensagem de sempre, quando o OCR esta desligado ou tambem nao acha texto.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise MaterialError(f"Nao consegui ler o PDF: {exc}") from exc

    try:
        return from_pages(reader.pages)
    except MaterialError:
        if not ocr_service.is_available():
            raise
        logger.info("PDF sem texto extraivel; tentando OCR")
        return _pdf_via_ocr(data)


def _pdf_via_ocr(data: bytes) -> ExtractedMaterial:
    """Le um PDF digitalizado pelas imagens das paginas.

    Mantem `rewrap`: pagina escaneada e documento corrido, e o OCR devolve uma
    linha por linha impressa - as mesmas quebras por largura de pagina que a
    leitura normal de PDF ja desfaz.
    """
    blocos, cortado = ocr_service.text_from_pdf(data)
    if not any(bloco.strip() for bloco in blocos):
        # Sem texto nem por OCR: o motivo honesto continua sendo o original.
        raise MaterialError(SCANNED_HINT)

    extraido = from_blocks(blocos, source_type="pdf-ocr", empty_hint=SCANNED_HINT)
    if cortado:
        # O teto de paginas cortou o material tanto quanto MAX_CHARS cortaria, e
        # a interface ja sabe avisar sobre isso.
        extraido = replace(extraido, truncated=True)
    return extraido


def extract_image_sync(data: bytes) -> ExtractedMaterial:
    """Texto de uma imagem: foto do quadro, pagina de livro fotografada.

    Sem `rewrap`, ao contrario do PDF digitalizado: foto de quadro ou de slide
    costuma ser lista de topicos, e juntar as linhas viraria uma frase so.
    """
    if not ocr_service.is_available():
        raise MaterialError(
            "Leitura de imagem indisponivel: o OCR esta desligado ou nao "
            "instalado neste servidor."
        )

    texto = ocr_service.text_from_image(data)
    if not texto.strip():
        raise MaterialError(
            "Nao consegui ler texto nessa imagem. Foto tremida ou de longe "
            "costuma ser a causa."
        )

    return from_blocks([texto], source_type="image-ocr", rewrap=False)


def from_pages(pages: Any) -> ExtractedMaterial:
    """Adapta as paginas do pypdf para o caminho comum.

    O `try` por pagina fica aqui, e nao em `from_blocks`, porque e defeito de
    PDF: uma fonte corrompida numa pagina nao pode perder o material inteiro.
    """
    blocos: list[str] = []
    for index, page in enumerate(pages):
        try:
            blocos.append(page.extract_text() or "")
        except Exception as exc:
            logger.warning(f"Pagina {index + 1} do material ilegivel: {exc}")

    return from_blocks(blocos, source_type="pdf", empty_hint=SCANNED_HINT)


# --- Documento de texto (DOCX) ----------------------------------------------


def extract_docx_sync(data: bytes) -> ExtractedMaterial:
    """Texto de um .docx: paragrafos e tabelas, na ordem em que aparecem.

    O documento vira um bloco so porque .docx nao tem pagina - a paginacao so
    existe depois que um editor renderiza o arquivo.
    """
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise MaterialError(
            "Leitura de .docx indisponivel: falta a dependencia python-docx."
        ) from exc

    try:
        documento = Document(io.BytesIO(data))
    except Exception as exc:
        raise MaterialError(f"Nao consegui ler o DOCX: {exc}") from exc

    linhas: list[str] = [p.text for p in documento.paragraphs]
    for tabela in documento.tables:
        for linha in tabela.rows:
            celulas = [c.text.strip() for c in linha.cells if c.text.strip()]
            if celulas:
                linhas.append(" | ".join(celulas))

    return from_blocks(
        ["\n\n".join(linhas)], source_type="docx", rewrap=False
    )


# --- Slide (PPTX) ------------------------------------------------------------


def extract_pptx_sync(data: bytes) -> ExtractedMaterial:
    """Texto de um .pptx, um bloco por slide.

    Slide e a melhor fonte de quiz que existe no material do professor: ja vem
    dividido por topico. As notas do apresentador entram junto - e nelas que
    costuma estar a explicacao que o bullet resume.
    """
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise MaterialError(
            "Leitura de .pptx indisponivel: falta a dependencia python-pptx."
        ) from exc

    try:
        apresentacao = Presentation(io.BytesIO(data))
    except Exception as exc:
        raise MaterialError(f"Nao consegui ler o PPTX: {exc}") from exc

    blocos: list[str] = []
    for numero, slide in enumerate(apresentacao.slides, start=1):
        linhas: list[str] = []
        for forma in slide.shapes:
            try:
                if forma.has_text_frame:
                    linhas.extend(
                        p.text.strip()
                        for p in forma.text_frame.paragraphs
                        if p.text.strip()
                    )
                elif forma.has_table:
                    for linha in forma.table.rows:
                        celulas = [
                            c.text.strip() for c in linha.cells if c.text.strip()
                        ]
                        if celulas:
                            linhas.append(" | ".join(celulas))
            except Exception as exc:
                # Uma forma quebrada nao pode perder o slide, muito menos o deck.
                logger.warning(f"Forma ilegivel no slide {numero}: {exc}")

        if slide.has_notes_slide:
            try:
                nota = (slide.notes_slide.notes_text_frame.text or "").strip()
                if nota:
                    linhas.append(nota)
            except Exception as exc:
                logger.warning(f"Notas ilegiveis no slide {numero}: {exc}")

        blocos.append("\n".join(linhas))

    return from_blocks(blocos, source_type="pptx", rewrap=False)


# --- Texto puro (TXT, MD) ----------------------------------------------------


def extract_plain_sync(data: bytes, source_type: str = "txt") -> ExtractedMaterial:
    """Texto puro, ja aproveitavel como veio.

    Sem `rewrap`: em Markdown a quebra de linha separa itens de lista, e junta-la
    transformaria a lista numa frase so.
    """
    try:
        texto = data.decode("utf-8")
    except UnicodeDecodeError:
        # Arquivo salvo no Windows costuma vir em latin-1; recusar por causa de
        # um acento seria pior que aproximar o caractere.
        texto = data.decode("latin-1", errors="replace")

    return from_blocks([texto], source_type=source_type, rewrap=False)


def extract_markdown_sync(data: bytes) -> ExtractedMaterial:
    return extract_plain_sync(data, source_type="md")


# --- Registro dos formatos ---------------------------------------------------

#: Extensao -> extrator sincrono. Registrar aqui e o unico passo para um formato
#: novo passar a valer no upload, na validacao e na mensagem de erro.
_EXTRACTORS: dict[str, Callable[[bytes], ExtractedMaterial]] = {
    ".pdf": extract_pdf_sync,
    ".docx": extract_docx_sync,
    ".pptx": extract_pptx_sync,
    ".txt": extract_plain_sync,
    ".md": extract_markdown_sync,
    ".markdown": extract_markdown_sync,
    # Imagem so vira material com OCR; sem ele o extrator recusa explicando.
    **{ext: extract_image_sync for ext in ocr_service.IMAGE_EXTENSIONS},
}

#: Ordenada para a mensagem de erro e para o seletor de arquivo sairem estaveis.
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(_EXTRACTORS))


def extension_of(filename: str) -> str:
    """Extensao normalizada, com ponto e em minuscula. Vazia se nao houver."""
    nome = (filename or "").strip().lower()
    if "." not in nome:
        return ""
    return "." + nome.rsplit(".", 1)[-1]


def is_supported(filename: str) -> bool:
    return extension_of(filename) in _EXTRACTORS


async def extract(data: bytes, filename: str) -> ExtractedMaterial:
    """Extrai o texto de um material sem segurar o event loop.

    Raises:
        MaterialError: formato nao suportado, arquivo ilegivel, vazio ou sem
            texto extraivel.
    """
    if not data:
        raise MaterialError("Arquivo vazio.")

    extensao = extension_of(filename)
    extrator = _EXTRACTORS.get(extensao)
    if extrator is None:
        aceitos = ", ".join(SUPPORTED_EXTENSIONS)
        recebido = extensao or "sem extensao"
        raise MaterialError(
            f"Formato nao suportado ({recebido}). Aceito: {aceitos}."
        )

    return await asyncio.to_thread(extrator, data)


async def extract_pdf(data: bytes) -> ExtractedMaterial:
    """Atalho para quem ja sabe que o arquivo e PDF.

    Raises:
        MaterialError: arquivo ilegivel, vazio ou sem texto extraivel.
    """
    if not data:
        raise MaterialError("Arquivo vazio.")
    return await asyncio.to_thread(extract_pdf_sync, data)
