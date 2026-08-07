"""Picks a default LLM for chat requests that don't specify one.

Priority: free/local providers first, then paid providers with confirmed
remaining credit, then paid providers with no balance signal. Providers
known to be out of credit never reach here (llm_status_service already
excludes them from "available").

Sobre a rota por tarefa: a regra de custo continua sendo a base. O tipo de
tarefa so entra para *rebaixar* provedores fracos em pedidos exigentes — mandar
uma tarefa de codigo para um modelo local de 3B economiza credito e devolve
resposta inutil, o que nao e economia.
"""

import re
import unicodedata

from .llm_status_service import get_llm_statuses

FREE_LOCAL_LLMS = {"llama", "localai"}

# Provedores que aguentam raciocinio longo, codigo e instrucao complexa.
STRONG_LLMS = {
    "claude",
    "gpt",
    "deepseek",
    "grok",
    "gemini",
    "together",
    "openrouter",
}

# Tarefas em que um modelo fraco costuma devolver resposta inaproveitavel.
DEMANDING_TASKS = {"code"}

TASK_KINDS = ("general", "code", "study", "calendar")

_CODE_PATTERNS = (
    r"\bcodig\w+", r"\bcod\w*\b", r"\bfuncao\b", r"\bfuncoes\b", r"\bclasse\b",
    r"\bbug\b", r"\berro\b", r"\bstack\s*trace\b", r"\bexception\b",
    r"\brefator\w+", r"\bimplement\w+", r"\bdebug\w*", r"\bcompil\w+",
    r"\btest\w*\s+unitari\w+", r"\bpython\b", r"\bjavascript\b", r"\btypescript\b",
    r"\bdart\b", r"\bflutter\b", r"\bsql\b", r"\bapi\b", r"\bendpoint\b",
    r"\bgit\b", r"\bdocker\b", r"\bscript\b", r"\brepositori\w+",
)

_STUDY_PATTERNS = (
    r"\baula\b", r"\baulas\b", r"\bprofessor\w*\b", r"\bmateria\b",
    r"\bdisciplina\b", r"\bexplic\w+\s+(?:sobre|que|o)\b", r"\bfalou\s+sobre\b",
    r"\bconteud\w+\b", r"\bprova\b", r"\bavaliacao\b", r"\bexercici\w+",
    r"\btrabalho\s+da\s+\w+", r"\banotac\w+", r"\bresumo\s+da\s+aula\b",
    r"\bna\s+ultima\s+aula\b", r"\bo\s+que\s+(?:foi|vimos|estudamos)\b",
)

_CALENDAR_PATTERNS = (
    r"\bagenda\b", r"\breuniao\b", r"\breunioes\b", r"\bcompromiss\w+",
    r"\bevento\b", r"\bmarcar\b", r"\bagendar\b", r"\bhorari\w+",
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _matches(text: str, patterns: tuple[str, ...]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text))


def detect_task(message: str) -> str:
    """Classifica o pedido para orientar a escolha do provedor.

    Heuristica proposital em vez de LLM: classificar com modelo custaria uma
    chamada extra so para decidir quem responde, o que anula a economia que a
    rota deveria trazer.
    """
    text = _normalize(message)
    if not text.strip():
        return "general"

    scores = {
        "code": _matches(text, _CODE_PATTERNS),
        "study": _matches(text, _STUDY_PATTERNS),
        "calendar": _matches(text, _CALENDAR_PATTERNS),
    }
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] > 0 else "general"


def _tier(provider: str, balance_ok: bool | None) -> int:
    if provider in FREE_LOCAL_LLMS:
        return 0
    if balance_ok is True:
        return 1
    if balance_ok is None:
        return 2
    return 3


def _task_tier(provider: str, balance_ok: bool | None, task: str) -> int:
    base = _tier(provider, balance_ok)
    if task in DEMANDING_TASKS and provider not in STRONG_LLMS:
        # Rebaixa, mas nao elimina: se o local for a unica opcao, ele responde.
        return base + 10
    return base


async def pick_auto_llm(candidates: list[str], task: str = "general") -> str:
    if not candidates:
        return ""
    statuses = await get_llm_statuses()
    ranked = sorted(
        candidates,
        key=lambda provider: (
            _task_tier(
                provider,
                statuses[provider].balance_ok if provider in statuses else None,
                task,
            ),
            candidates.index(provider),
        ),
    )
    return ranked[0]


async def pick_for_message(candidates: list[str], message: str) -> tuple[str, str]:
    """Detecta a tarefa e devolve (provedor, tarefa) numa chamada so."""
    task = detect_task(message)
    return await pick_auto_llm(candidates, task), task
