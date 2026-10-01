"""Transcricao pronta de reuniao online, vinda do Teams ou do Meet.

Quem gravou a reuniao pela propria plataforma ja tem o texto, e com uma coisa
que o Whisper nao da: o nome de quem falou. Este modulo so arruma esse texto
para ele entrar como trechos de uma gravacao - tira o que e do formato
(cabecalho, horarios, marcacao de legenda), junta as falas seguidas da mesma
pessoa e corta em blocos do tamanho de um trecho de audio.

Nada aqui fala com banco ou modelo: e texto entrando e texto saindo.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List, Sequence

#: Tamanho de um bloco importado. Um minuto de fala transcrita da perto de mil
#: caracteres; ficar nessa ordem mantem a busca e o resumo tratando texto
#: importado como tratam o gravado.
BLOCK_MAX_CHARS = 1500

#: Extensoes de texto puro aceitas alem do .docx, que tem extrator proprio.
TEXT_EXTENSIONS: tuple[str, ...] = (".vtt", ".srt", ".txt", ".md")

_CUE_TIMING = re.compile(r"-->")
_TIMESTAMP_ONLY = re.compile(r"^\(?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\)?$")
_VOICE_TAG = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
# "Nome Sobrenome: fala". Curto e comecando por letra, para nao tomar por nome
# uma frase inteira que por acaso tem dois-pontos no meio.
_SPEAKER_LINE = re.compile(r"^([^\W\d_][^:\n]{0,59}?):\s+(\S.*)$")
# "NOME SOBRENOME   13:25", como o .docx do Teams abre cada fala. O nome nao
# leva pontuacao: e o que o separa de uma frase que termina em horario.
_TIMED_SPEAKER = re.compile(
    r"^([^\W\d_][^.,;:!?\n]{1,59}?)(\s+)\(?\d{1,2}:\d{2}(?::\d{2})?\)?$"
)
# Avisos que o Teams escreve no proprio documento e que nao sao fala.
_SYSTEM_NOTE = re.compile(
    r"\b(?:started|stopped) transcription$"
    r"|\b(?:iniciou|interrompeu|parou|encerrou) a transcri[cç][aã]o$",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Turn:
    """Uma fala. `speaker` vazio quando o texto nao diz de quem e."""

    speaker: str
    text: str


def parse_transcript(raw: str) -> List[Turn]:
    """Le a transcricao em falas, na ordem, ja com as seguidas reunidas."""
    text = (raw or "").replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    turns = _parse_cues(text) if _CUE_TIMING.search(text) else _parse_lines(text)
    return _merge(turns)


def split_blocks(turns: Sequence[Turn], max_chars: int = BLOCK_MAX_CHARS) -> List[str]:
    """Agrupa as falas em blocos, sem partir uma fala que cabe inteira.

    Fala maior que o bloco e cortada em fim de frase, e cada pedaco repete o
    nome: um bloco lido sozinho, na busca, ainda diz quem estava falando.
    """
    blocks: List[str] = []
    current: List[str] = []
    size = 0
    for turn in turns:
        for piece in _pieces(turn, max_chars):
            if current and size + len(piece) + 1 > max_chars:
                blocks.append("\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece) + 1
    if current:
        blocks.append("\n".join(current))
    return blocks


def speakers_of(turns: Sequence[Turn]) -> List[str]:
    """Quem falou, na ordem da primeira fala e sem repetir."""
    seen: dict[str, None] = {}
    for turn in turns:
        if turn.speaker:
            seen.setdefault(turn.speaker, None)
    return list(seen)


def decode_text(data: bytes) -> str:
    """Bytes de um arquivo de texto. Latin-1 quando nao e UTF-8 valido."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


# --- Formatos ----------------------------------------------------------------


def _parse_cues(text: str) -> List[Turn]:
    """VTT e SRT: so vale o que vem depois da linha de horario de cada bloco."""
    turns: List[Turn] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.split("\n")]
        timing = next(
            (index for index, line in enumerate(lines) if _CUE_TIMING.search(line)),
            None,
        )
        if timing is None:
            # Cabecalho WEBVTT, NOTE, STYLE: nao e fala.
            continue
        speaker = ""
        spoken: List[str] = []
        for line in lines[timing + 1:]:
            voice = _VOICE_TAG.search(line)
            if voice:
                speaker = _clean(voice.group(1))
            clean = _clean(_ANY_TAG.sub("", line))
            if clean:
                spoken.append(clean)
        content = " ".join(spoken)
        if not content:
            continue
        if not speaker:
            named = _SPEAKER_LINE.match(content)
            if named:
                speaker, content = _clean(named.group(1)), named.group(2).strip()
        turns.append(Turn(speaker, content))
    return turns


def _parse_lines(text: str) -> List[Turn]:
    """Texto corrido: "Nome: fala" (Meet) ou "Nome   13:25" e a fala abaixo
    (.docx do Teams) abrem uma fala; as linhas seguintes continuam nela."""
    turns: List[Turn] = []
    paragraph_start = True
    for raw_line in text.split("\n"):
        line = _clean(raw_line)
        if not line:
            paragraph_start = True
            continue
        at_start, paragraph_start = paragraph_start, False
        if _TIMESTAMP_ONLY.match(line) or _SYSTEM_NOTE.search(line):
            continue

        timed = _TIMED_SPEAKER.match(html.unescape(raw_line).strip())
        # Com um espaco so entre nome e horario, vale apenas no comeco do
        # paragrafo: no meio dele e mais provavel uma frase que acaba em hora.
        if timed and (len(timed.group(2)) >= 2 or at_start):
            turns.append(Turn(_clean(timed.group(1)), ""))
            continue

        named = _SPEAKER_LINE.match(line)
        if named:
            turns.append(Turn(_clean(named.group(1)), named.group(2).strip()))
        elif turns:
            last = turns[-1]
            turns[-1] = Turn(last.speaker, f"{last.text} {line}".strip())
        else:
            turns.append(Turn("", line))
    return [turn for turn in turns if turn.text]


def _merge(turns: Sequence[Turn]) -> List[Turn]:
    merged: List[Turn] = []
    for turn in turns:
        if merged and merged[-1].speaker == turn.speaker:
            merged[-1] = Turn(
                turn.speaker, f"{merged[-1].text} {turn.text}".strip()
            )
        else:
            merged.append(turn)
    return merged


def _clean(value: str) -> str:
    return " ".join(html.unescape(value or "").split())


def _pieces(turn: Turn, max_chars: int) -> List[str]:
    prefix = f"{turn.speaker}: " if turn.speaker else ""
    room = max(200, max_chars - len(prefix))
    if len(turn.text) <= room:
        return [prefix + turn.text]

    pieces: List[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(turn.text):
        while len(sentence) > room:
            # Frase sem ponto final nenhum (transcricao automatica faz isso):
            # corta no ultimo espaco que cabe.
            cut = sentence.rfind(" ", 0, room)
            cut = cut if cut > 0 else room
            if current:
                pieces.append(prefix + current)
                current = ""
            pieces.append(prefix + sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + len(sentence) + 1 > room:
            pieces.append(prefix + current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(prefix + current)
    return pieces
