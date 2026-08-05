"""Regras do modo educacao: resumo da aula e pontuacao extra de alunos.

A interface envia blocos de audio ao longo da aula. Cada bloco vira um trecho
de transcricao, e sobre esse texto rodamos duas coisas independentes: a
indexacao no Qdrant (para o resumo depois recuperar contexto) e a extracao de
pontuacoes extras citadas pelo professor.
"""

import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from ..core.config import get_settings
from .llm_routing_service import pick_auto_llm
from .llm_service import dispatch_single

settings = get_settings()

# Abaixo disso o nome ouvido e diferente demais do cadastro para ser a mesma
# pessoa; o registro fica sem student_id e aparece como pendente de revisao.
_NAME_MATCH_THRESHOLD = 0.82
_MAX_POINTS_PER_ENTRY = 100.0


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", stripped).split())


async def resolve_llm(preferred: Optional[str] = None) -> str:
    if preferred and preferred not in {"auto", ""}:
        return preferred
    return await pick_auto_llm(settings.active_llms) or "llama"


# --- Casamento de nomes contra a turma ------------------------------------


def _roster_keys(student: Dict[str, Any]) -> List[str]:
    keys = [normalize_name(student.get("name", ""))]
    for alias in student.get("aliases") or []:
        normalized = normalize_name(str(alias))
        if normalized:
            keys.append(normalized)
    return [key for key in keys if key]


def match_student(
    heard_name: str,
    roster: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Casa o nome ouvido no audio com o cadastro da turma.

    O Whisper erra nomes proprios com frequencia ("Tiago"/"Thiago",
    "Wesley"/"Uesley"), entao alem do nome cheio aceitamos apelidos, primeiro
    nome unico na turma e similaridade textual.
    """
    heard = normalize_name(heard_name)
    result: Dict[str, Any] = {
        "student_id": None,
        "student_name": (heard_name or "").strip(),
        "confidence": 0.0,
    }
    if not heard or not roster:
        return result

    for student in roster:
        if heard in _roster_keys(student):
            return {
                "student_id": student.get("id"),
                "student_name": student.get("name", heard_name),
                "confidence": 1.0,
            }

    # Professor costuma citar so o primeiro nome. So aceitamos quando ele
    # identifica uma unica pessoa da turma — havendo duas Marias, fica pendente.
    first = heard.split()[0]
    by_first = [
        student
        for student in roster
        if any(key.split()[0] == first for key in _roster_keys(student))
    ]
    if len(by_first) == 1:
        return {
            "student_id": by_first[0].get("id"),
            "student_name": by_first[0].get("name", heard_name),
            "confidence": 0.9,
        }

    # Primeiro nome mal transcrito ("Tiago" por "Thiago"): comparar o token
    # ouvido com o nome completo derruba a similaridade, entao comparamos
    # primeiro nome contra primeiro nome.
    if not by_first:
        near_first = []
        for student in roster:
            score = max(
                (
                    SequenceMatcher(None, first, key.split()[0]).ratio()
                    for key in _roster_keys(student)
                ),
                default=0.0,
            )
            if score >= _NAME_MATCH_THRESHOLD:
                near_first.append((score, student))
        if len(near_first) == 1:
            score, student = near_first[0]
            return {
                "student_id": student.get("id"),
                "student_name": student.get("name", heard_name),
                "confidence": round(score * 0.9, 3),
            }

    best_score = 0.0
    best_student: Optional[Dict[str, Any]] = None
    for student in roster:
        for key in _roster_keys(student):
            score = SequenceMatcher(None, heard, key).ratio()
            if score > best_score:
                best_score = score
                best_student = student

    if best_student is not None and best_score >= _NAME_MATCH_THRESHOLD:
        return {
            "student_id": best_student.get("id"),
            "student_name": best_student.get("name", heard_name),
            "confidence": round(best_score, 3),
        }

    result["confidence"] = round(best_score, 3)
    return result


# --- Extracao de pontuacao extra ------------------------------------------


_POINTS_SYSTEM_PROMPT = (
    "Voce extrai pontuacoes extras concedidas por um professor durante a aula. "
    "Responda SEMPRE com JSON valido, sem markdown e sem texto fora do JSON."
)


def _points_prompt(text: str, roster: Sequence[Dict[str, Any]]) -> str:
    names = [str(student.get("name", "")) for student in roster if student.get("name")]
    roster_block = (
        "Alunos da turma (use exatamente estes nomes quando reconhecer o aluno):\n"
        + "\n".join(f"- {name}" for name in names)
        if names
        else "Nao ha cadastro de turma; transcreva o nome como foi falado."
    )

    return (
        f"{roster_block}\n\n"
        "Trecho da transcricao da aula:\n"
        f'"""\n{text}\n"""\n\n'
        "Liste apenas pontuacoes extras que o professor concedeu explicitamente "
        "a um aluno neste trecho. Ignore notas de prova, medias, chamadas, "
        "combinados futuros e hipoteses (\"quem responder ganha ponto\" sem "
        "alguem receber). Se nada foi concedido, devolva a lista vazia.\n\n"
        "Formato exato:\n"
        '{"pontuacoes": [{"aluno": "nome", "pontos": 0.5, '
        '"motivo": "por que recebeu", "trecho": "frase do professor"}]}'
    )


def _parse_json_object(raw: str) -> Dict[str, Any]:
    """Extrai o objeto JSON mesmo com cercas de markdown ou texto em volta."""
    content = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_points(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        points = float(value)
    else:
        text = str(value or "").strip().replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        points = float(match.group())
    if points <= 0 or points > _MAX_POINTS_PER_ENTRY:
        return None
    return round(points, 3)


async def extract_points(
    *,
    text: str,
    roster: Sequence[Dict[str, Any]],
    llm: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Devolve as pontuacoes extras citadas no trecho, ja casadas com a turma."""
    if not text.strip():
        return []

    provider = await resolve_llm(llm)
    response = await dispatch_single(
        provider,
        _points_prompt(text, roster),
        [],
        _POINTS_SYSTEM_PROMPT,
    )
    if response.is_error:
        logger.warning(f"Extracao de pontos falhou ({provider}): {response.content}")
        return []

    payload = _parse_json_object(response.content)
    raw_entries = payload.get("pontuacoes")
    if not isinstance(raw_entries, list):
        return []

    entries: List[Dict[str, Any]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        heard_name = str(item.get("aluno") or "").strip()
        points = _coerce_points(item.get("pontos"))
        if not heard_name or points is None:
            continue

        match = match_student(heard_name, roster)
        entries.append({
            "student_id": match["student_id"],
            "student_name": match["student_name"],
            "heard_name": heard_name,
            "points": points,
            "reason": str(item.get("motivo") or "").strip() or None,
            "quote": str(item.get("trecho") or "").strip() or None,
            "confidence": match["confidence"],
        })
    return entries


def is_duplicate_point(
    entry: Dict[str, Any],
    existing: Sequence[Dict[str, Any]],
) -> bool:
    """Evita gravar duas vezes a mesma concessao.

    Blocos de audio consecutivos podem repetir a mesma frase quando o corte cai
    no meio dela, e o LLM entao extrai a concessao duas vezes.
    """
    name = normalize_name(entry.get("student_name", ""))
    points = float(entry.get("points") or 0)
    quote = normalize_name(entry.get("quote") or "")
    reason = normalize_name(entry.get("reason") or "")

    for item in existing:
        if normalize_name(item.get("student_name", "")) != name:
            continue
        if float(item.get("points") or 0) != points:
            continue
        other_quote = normalize_name(item.get("quote") or "")
        other_reason = normalize_name(item.get("reason") or "")
        if quote and other_quote and quote == other_quote:
            return True
        if reason and other_reason and reason == other_reason:
            return True
        if not quote and not reason and not other_quote and not other_reason:
            return True
    return False


# --- Resumo da aula --------------------------------------------------------


_SUMMARY_SYSTEM_PROMPT = (
    "Voce resume aulas a partir da transcricao do audio. Escreva em portugues "
    "brasileiro, de forma objetiva e fiel ao que foi dito. Nunca invente "
    "conteudo que nao esta na transcricao."
)


def _summary_prompt(
    *,
    subject: str,
    title: str,
    transcript: str,
    focus: str,
    partial: bool = False,
) -> str:
    header = f"Disciplina: {subject}"
    if title:
        header += f"\nAula: {title}"
    extra = f"\nDe atencao especial a: {focus}" if focus.strip() else ""

    if partial:
        return (
            f"{header}{extra}\n\n"
            "Este e um trecho de uma aula longa. Resuma o trecho preservando "
            "termos tecnicos, definicoes, exemplos e qualquer tarefa ou data "
            "citada. Nao escreva introducao nem conclusao.\n\n"
            f'Trecho:\n"""\n{transcript}\n"""'
        )

    return (
        f"{header}{extra}\n\n"
        "Monte o resumo da aula a partir da transcricao, nesta estrutura:\n"
        "## Resumo\n(2 a 4 paragrafos com o fio condutor da aula)\n"
        "## Principais topicos\n(lista com os conceitos trabalhados)\n"
        "## Definicoes e formulas\n(o que foi enunciado literalmente; omita a "
        "secao se nao houver)\n"
        "## Tarefas e avisos\n(trabalhos, prazos, datas de prova; omita se nao "
        "houver)\n"
        "## Duvidas levantadas\n(perguntas da turma e as respostas; omita se "
        "nao houver)\n\n"
        "Se a transcricao estiver truncada ou confusa em algum ponto, diga isso "
        "em vez de preencher com suposicao.\n\n"
        f'Transcricao:\n"""\n{transcript}\n"""'
    )


def _windows(texts: Sequence[str], max_chars: int) -> List[str]:
    windows: List[str] = []
    current: List[str] = []
    size = 0
    for text in texts:
        piece = text.strip()
        if not piece:
            continue
        if size + len(piece) > max_chars and current:
            windows.append("\n".join(current))
            current = []
            size = 0
        current.append(piece)
        size += len(piece) + 1
    if current:
        windows.append("\n".join(current))
    return windows


async def generate_summary(
    *,
    subject: str,
    title: str,
    segments: Sequence[str],
    llm: Optional[str] = None,
    focus: str = "",
) -> Dict[str, Any]:
    """Resume a aula, condensando em duas etapas quando ela e longa."""
    texts = [text for text in segments if text and text.strip()]
    if not texts:
        return {"summary": "", "llm": "", "used_segments": 0}

    provider = await resolve_llm(llm)
    max_chars = max(2000, settings.education_summary_max_chars)
    chunks = _windows(texts, max_chars)

    if len(chunks) > 1:
        # Aula de 2h nao cabe na janela de contexto de um modelo local, entao
        # resumimos cada bloco e depois resumimos os resumos.
        partials: List[str] = []
        for chunk in chunks:
            response = await dispatch_single(
                provider,
                _summary_prompt(
                    subject=subject,
                    title=title,
                    transcript=chunk,
                    focus=focus,
                    partial=True,
                ),
                [],
                _SUMMARY_SYSTEM_PROMPT,
            )
            if response.is_error:
                logger.warning(
                    f"Resumo parcial falhou ({provider}): {response.content}"
                )
                continue
            partials.append(response.content.strip())

        if not partials:
            return {"summary": "", "llm": provider, "used_segments": 0}
        transcript = "\n\n".join(partials)
    else:
        transcript = chunks[0]

    response = await dispatch_single(
        provider,
        _summary_prompt(
            subject=subject,
            title=title,
            transcript=transcript,
            focus=focus,
        ),
        [],
        _SUMMARY_SYSTEM_PROMPT,
    )
    if response.is_error:
        logger.warning(f"Resumo falhou ({provider}): {response.content}")
        return {"summary": "", "llm": provider, "used_segments": 0, "error": response.content}

    return {
        "summary": response.content.strip(),
        "llm": provider,
        "used_segments": len(texts),
    }
