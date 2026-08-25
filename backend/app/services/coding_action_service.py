"""Reconhece pedido de mexer em codigo e monta a acao para a interface.

O backend nao le nem escreve arquivo do usuario: quem tem o workspace e a
interface. Aqui so se identifica a intencao e o alvo, e a acao volta para ser
confirmada e executada na maquina.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_LOCAL_CONTEXT_MARKERS = (
    "contexto local do workspace",
    "workspace capturado pela interface",
    "snapshot local do projeto",
    "resultado da inspecao do workspace",
)


def build_coding_action(message: str) -> dict[str, Any] | None:
    """Monta a acao de codigo a partir da mensagem.

    Args:
        message: pedido do usuario, ja com o contexto de workspace que a interface
            anexou quando havia.

    Returns:
        A acao proposta, ou `None` quando a mensagem nao pede alteracao de codigo.
    """
    text = _normalize(message)
    if not text or any(marker in text for marker in _LOCAL_CONTEXT_MARKERS):
        return None

    codex_terms = (
        "codex",
        "modo codex",
        "agente de codigo",
        "agente de desenvolvimento",
        "coding agent",
    )
    project_terms = (
        "projeto",
        "repo",
        "repositorio",
        "workspace",
        "codigo",
        "fonte",
        "arquivo",
        "arquivos",
        "backend",
        "frontend",
        "flutter",
        "python",
        "api",
        "bug",
        "erro",
        "teste",
        "testes",
        "implemente",
        "corrija",
        "refatore",
    )
    request_terms = (
        "analise",
        "analisar",
        "verifique",
        "verificar",
        "cheque",
        "checar",
        "ajude",
        "ajudar",
        "auxilie",
        "corrija",
        "corrigir",
        "implemente",
        "implementar",
        "edite",
        "editar",
        "refatore",
        "refatorar",
        "rode",
        "rodar",
        "execute",
        "executar",
        "trabalhar",
        "trabalhe",
    )

    wants_codex = any(term in text for term in codex_terms)
    wants_project = any(_contains_term(text, term) for term in project_terms)
    wants_help = any(_contains_term(text, term) for term in request_terms)

    if not wants_codex and not (wants_project and wants_help):
        return None

    return {
        "type": "coding_action",
        "action_id": "inspect_workspace",
        "name": "Inspecionar workspace local",
        "description": (
            "Le estrutura e arquivos importantes de um projeto local para a IA "
            "trabalhar com contexto real, como um assistente de codigo."
        ),
        "risk_level": "low",
        "requires_confirmation": True,
        "arguments": {
            "query": message.strip(),
            "max_files": 320,
            "max_file_chars": 8000,
            "max_total_chars": 26000,
        },
    }


def _contains_term(text: str, term: str) -> bool:
    if " " in term:
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}\b", text))


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).strip()
