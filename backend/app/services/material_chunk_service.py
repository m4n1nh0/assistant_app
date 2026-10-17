"""Divisao do material em blocos por titulo.

O texto extraido de uma apostila e uma coluna so. Para indexar, estruturar e sortear
conteudo de prova, ele precisa virar pedacos que tenham sentido sozinhos. O corte
respeita os titulos: um bloco nao atravessa a fronteira de um capitulo, e leva o caminho
de titulos ("Capitulo 1 > 1.1 Elementos") como contexto.

Blocos maiores que o teto sao partidos em paragrafos, com uma sobreposicao curta entre
eles para uma ideia cortada ao meio aparecer inteira em um dos dois lados. Um bloco menor
que o piso e juntado ao vizinho da mesma secao, para nao indexar um titulo sozinho.

A heuristica de titulo e a mesma do portal do aluno (`structure()` em
`routers/student_portal.py`): linha curta, sem pontuacao final, em caixa alta, numerada
ou iniciada por "Capitulo", "Unidade" etc.

O texto original fica em `materials.content`; os blocos sao derivados e se refazem a
qualquer momento com `replace_chunks`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import MaterialChunkModel, MaterialModel

#: Teto de um bloco. Cabe com folga numa janela de embedding e num prompt de questao.
MAX_CHARS = 1800
#: Abaixo disso o bloco e juntado ao anterior da mesma secao.
MIN_CHARS = 300
#: Quanto do fim de um bloco repete no comeco do proximo, quando o corte e no meio de uma secao.
OVERLAP = 200

_BULLET = re.compile(r"^\s*(?:[-*•▪◦–]|\d{1,2}[.)])\s+")
_NUMBERED = re.compile(r"^\d+(\.\d+)*\.?\s+\S")
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_KEYWORD = re.compile(r"^(cap[ií]tulo|unidade|aula|tema|se[cç][aã]o|m[oó]dulo)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Chunk:
    sequence: int
    heading_path: str
    text: str


def is_heading(line: str, strict: bool = False) -> bool:
    """Linha que parece titulo.

    No modo estrito (texto de PDF que chegou picado, uma palavra por bloco) "linha curta sem
    ponto" nao diz nada, e so valem titulo em caixa alta, numerado ou com "Capitulo" etc.
    """
    text = line.strip()
    if not text or len(text) > 90 or text[-1] in ".;,:!?" or _BULLET.match(text):
        return False
    words = len(text.split())
    if words > 12 or (strict and words < 2):
        return False
    shouty = text == text.upper() and re.search(r"[A-ZÀ-Ú]", text) is not None
    return bool(shouty or _KEYWORD.match(text) or _NUMBERED.match(text) or (not strict and words <= 8))


def _depth(heading: str) -> int:
    """Nivel do titulo: "1.2.3 x" e 3, "1.2 x" e 2, o resto e 1."""
    numbered = re.match(r"^(\d+(?:\.\d+)*)", heading)
    return numbered.group(1).count(".") + 1 if numbered else 1


def _is_fragmented(blocks: list[list[str]]) -> bool:
    """Mais de 30% dos blocos sao uma linha de ate 3 palavras: a extracao picou o texto."""
    if len(blocks) < 8:
        return False
    tiny = sum(1 for b in blocks if len(b) == 1 and len(b[0].split()) <= 3)
    return tiny / len(blocks) > 0.3


def _defragment(blocks: list[list[str]]) -> list[list[str]]:
    """Junta os pedacos em paragrafos: so fecha em fim de frase ou quando chega um titulo."""
    out: list[list[str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append([" ".join(buf)])
            buf.clear()

    for block in blocks:
        joined = " ".join(block)
        if is_heading(joined, strict=True):
            flush()
            out.append([joined])
            continue
        buf.append(joined)
        if re.search(r"""[.!?]["')\]]?$""", joined) or len(" ".join(buf)) > 700:
            flush()
    flush()
    return out


def _sections(text: str) -> list[tuple[str, str]]:
    """Pares (caminho de titulos, corpo) na ordem do documento."""
    path: list[tuple[int, str]] = []
    sections: list[tuple[str, str]] = []
    body: list[str] = []

    def flush() -> None:
        content = "\n\n".join(body).strip()
        if content:
            sections.append((" > ".join(h for _, h in path), content))
        body.clear()

    blocks = [
        [line.strip() for line in block.split("\n") if line.strip()]
        for block in re.split(r"\n\s*\n", text)
    ]
    blocks = [b for b in blocks if b]
    strict = _is_fragmented(blocks)
    if strict:
        blocks = _defragment(blocks)

    for lines in blocks:
        # Texto melhorado por IA: titulo marcado com "#", o nivel vem da quantidade de "#".
        marked = _MARKDOWN_HEADING.match(lines[0])
        if marked:
            flush()
            level = len(marked.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, marked.group(2).strip()))
            if len(lines) > 1:
                body.append("\n".join(lines[1:]))
            continue
        # Titulo e bloco de uma linha, ou a primeira linha seguida de corpo que nao e titulo.
        if is_heading(lines[0], strict) and (len(lines) == 1 or not is_heading(lines[1], strict)):
            flush()
            level = _depth(lines[0])
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, lines[0]))
            if len(lines) > 1:
                body.append("\n".join(lines[1:]))
            continue
        body.append("\n".join(lines))
    flush()
    return sections


def _split_long(body: str) -> list[str]:
    """Parte um corpo grande em paragrafos, repetindo o fim de cada parte na seguinte."""
    if len(body) <= MAX_CHARS:
        return [body]
    parts: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", body):
        # Paragrafo maior que o teto: corta em frases.
        pieces = [paragraph]
        if len(paragraph) > MAX_CHARS:
            pieces = re.split(r"(?<=[.!?])\s+", paragraph)
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > MAX_CHARS:
                parts.append(current)
                tail = current[-OVERLAP:]
                # Comeca a sobreposicao numa fronteira de palavra.
                tail = tail[tail.find(" ") + 1:] if " " in tail else ""
                current = f"{tail}\n\n{piece}" if tail else piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def split_into_chunks(text: str) -> list[Chunk]:
    """Corta o texto do material em blocos por titulo."""
    pieces: list[tuple[str, str]] = []
    for heading, body in _sections(text):
        for part in _split_long(body):
            if pieces and len(part) < MIN_CHARS and pieces[-1][0] == heading:
                pieces[-1] = (heading, f"{pieces[-1][1]}\n\n{part}")
            else:
                pieces.append((heading, part))
    return [Chunk(sequence=i, heading_path=h[:500], text=t) for i, (h, t) in enumerate(pieces)]


async def replace_chunks(
    db: AsyncSession, material: MaterialModel, content: str | None = None
) -> int:
    """Refaz os blocos do material. Devolve quantos ficaram. O commit e de quem chama.

    `content` e o texto a cortar quando ha uma versao melhorada por IA; sem ele, o original.
    """
    await db.execute(delete(MaterialChunkModel).where(MaterialChunkModel.material_id == material.id))
    chunks = split_into_chunks(content if content is not None else (material.content or ""))
    db.add_all([
        MaterialChunkModel(
            material_id=material.id, tutor_id=material.tutor_id,
            discipline_id=material.discipline_id, sequence=c.sequence,
            heading_path=c.heading_path, text=c.text, char_count=len(c.text), indexed=False)
        for c in chunks
    ])
    return len(chunks)


async def delete_chunks(db: AsyncSession, material_id: str) -> None:
    await db.execute(delete(MaterialChunkModel).where(MaterialChunkModel.material_id == material_id))
