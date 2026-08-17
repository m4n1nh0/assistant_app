"""Recognizes explicit requests to begin classroom workflows."""

import re
import unicodedata

from ..models.schemas import EducationOpenAction


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).strip()


_MODE_PATTERN = re.compile(
    r"\b(?:abr(?:a|ir)|ativ(?:a|ar)|entr(?:e|ar)|va\s+para|ir\s+para)\s+"
    r"(?:o\s+)?modo\s+(?:aula|educacao|educacional)\b"
)
_LESSON_PATTERN = re.compile(
    r"\b(?:vamos\s+|vou\s+)?(?:iniciar|inicie|comecar|comece|abrir|abra|dar\s+inicio)\s+"
    r"(?:a\s+|uma\s+|minha\s+)?aula\b|\bhora\s+de\s+(?:comecar|iniciar)\s+a\s+aula\b"
)
_ATTENDANCE_PATTERN = re.compile(
    r"\b(?:iniciar|inicie|comecar|comece|abrir|abra|fazer|faca|gerar|gere)\s+(?:a\s+)?chamada\s+"
    r"(?:da\s+turma|dos?\s+alunos?|de\s+presenca)\b|"
    r"\b(?:abrir|abra|iniciar|inicie|registrar|registre|fazer|faca)\s+(?:a\s+)?presenca\s+"
    r"(?:da\s+turma|dos?\s+alunos?)\b"
)


def build_education_open_action(message: str) -> EducationOpenAction | None:
    text = _normalize(message)
    if not text:
        return None
    if _ATTENDANCE_PATTERN.search(text):
        return EducationOpenAction(
            destination="attendance",
            reason="O pedido parece ser para iniciar a chamada da turma.",
        )
    if _MODE_PATTERN.search(text) or _LESSON_PATTERN.search(text):
        return EducationOpenAction(
            destination="lesson",
            reason="O pedido parece indicar o inicio de uma aula.",
        )
    return None
