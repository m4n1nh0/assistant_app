"""Catalogo de acoes de computador que o assistente pode propor.

Cada acao tem um `ComputerActionSpec` declarando id, rotulo, argumentos e
plataformas onde vale. O backend monta e valida a proposta; a execucao acontece
na interface - `run_action` existe so para recusar explicitamente a execucao no
servidor, deixando claro de quem e a responsabilidade.
"""

from __future__ import annotations

import platform
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


class ComputerActionError(ValueError):
    """Acao invalida, desconhecida ou nao executavel neste contexto."""
    pass


@dataclass(frozen=True)
class ComputerActionSpec:
    """Declaracao de uma acao de computador: id, rotulo, argumentos e plataformas."""
    id: str
    name: str
    description: str
    risk_level: str = "low"
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serializa a especificacao no formato devolvido pela API."""
        return asdict(self)


NETWORK_DIAGNOSTICS = ComputerActionSpec(
    id="network_diagnostics",
    name="Diagnostico de rede",
    description="Coleta IP local, gateway, DNS, IP externo e ping para analisar conectividade.",
)
SYSTEM_DIAGNOSTICS = ComputerActionSpec(
    id="system_diagnostics",
    name="Diagnostico do sistema",
    description="Coleta processos por RAM, uso de disco e informacoes basicas de memoria.",
)
SCRIPT_EXECUTION = ComputerActionSpec(
    id="run_script",
    name="Executar script local",
    description="Executa um script solicitado explicitamente pelo usuario no shell local.",
    risk_level="medium",
    requires_confirmation=True,
)

SAFE_ACTIONS = {
    NETWORK_DIAGNOSTICS.id: NETWORK_DIAGNOSTICS,
    SYSTEM_DIAGNOSTICS.id: SYSTEM_DIAGNOSTICS,
    SCRIPT_EXECUTION.id: SCRIPT_EXECUTION,
}

_ANALYSIS_MARKERS = (
    "resultado da acao local",
    "resultado da ação local",
    "saida da acao local",
    "resultado do script local",
    "saida do script local",
    "saída da ação local",
)

_HIGH_RISK_PATTERNS = (
    r"\brm\s+-rf\s+[/~*]",
    r"\bremove-item\b[\s\S]*\s-recurse\b[\s\S]*\s-force\b",
    r"\bdel\s+/[fsq]",
    r"\bformat\s+[a-z]:",
    r"\bshutdown\b|\brestart-computer\b|\bstop-computer\b",
    r"\bdiskpart\b|\bmkfs\.",
    r"\breg\s+delete\b",
)


def list_actions() -> list[ComputerActionSpec]:
    """Lista as acoes suportadas na plataforma atual."""
    return list(SAFE_ACTIONS.values())


def get_action(action_id: str) -> ComputerActionSpec:
    """Busca a especificacao de uma acao pelo id.

    Raises:
        ComputerActionError: quando o id nao existe.
    """
    action = SAFE_ACTIONS.get(action_id)
    if action is None:
        raise ComputerActionError(f"Acao local nao permitida: {action_id}")
    return action


def build_computer_action(message: str) -> dict[str, Any] | None:
    """Reconhece na mensagem uma acao de computador e a monta.

    Returns:
        A acao proposta, ou `None` quando a mensagem nao pede acao no computador.
    """
    text = _normalize(message)
    if not text or any(marker in text for marker in _ANALYSIS_MARKERS):
        return None

    network_terms = (
        "ip",
        "dns",
        "gateway",
        "ping",
        "rede",
        "internet",
        "conexao",
        "conectividade",
        "latencia",
        "wi fi",
        "wifi",
    )
    request_terms = (
        "verifique",
        "verificar",
        "diagnostico",
        "diagnosticar",
        "analise",
        "analisar",
        "teste",
        "testar",
        "cheque",
        "checar",
        "rode",
        "rodar",
        "execute",
        "executar",
        "qual",
        "mostre",
    )

    wants_network = any(_contains_term(text, term) for term in network_terms)
    wants_action = any(_contains_term(text, term) for term in request_terms)
    asks_own_ip = bool(re.search(r"\b(meu|minha)\s+ip\b", text))

    if wants_network and (wants_action or asks_own_ip):
        return {
            "type": "computer_action",
            "action_id": NETWORK_DIAGNOSTICS.id,
            "name": NETWORK_DIAGNOSTICS.name,
            "description": NETWORK_DIAGNOSTICS.description,
            "risk_level": NETWORK_DIAGNOSTICS.risk_level,
            "requires_confirmation": NETWORK_DIAGNOSTICS.requires_confirmation,
        }

    system_terms = (
        "ram",
        "memoria",
        "cpu",
        "processo",
        "processos",
        "disco",
        "discos",
        "armazenamento",
        "espaco",
        "hd",
        "ssd",
        "drive",
        "drives",
        "uso do sistema",
        "recursos",
    )
    wants_system = any(_contains_term(text, term) for term in system_terms)
    if wants_system and wants_action:
        return {
            "type": "computer_action",
            "action_id": SYSTEM_DIAGNOSTICS.id,
            "name": SYSTEM_DIAGNOSTICS.name,
            "description": SYSTEM_DIAGNOSTICS.description,
            "risk_level": SYSTEM_DIAGNOSTICS.risk_level,
            "requires_confirmation": SYSTEM_DIAGNOSTICS.requires_confirmation,
        }

    script_action = _build_script_action(message, text)
    if script_action:
        return script_action

    return None


async def run_action(action_id: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recusa executar a acao no backend, por design.

    A execucao pertence a interface desktop, que roda na maquina do usuario e pede
    confirmacao. Manter o metodo aqui torna a fronteira explicita em vez de
    implicita.

    Raises:
        ComputerActionError: sempre, com a explicacao de onde a acao deve rodar.
    """
    get_action(action_id)
    raise ComputerActionError(
        "Execucao local desativada no backend. A interface desktop deve executar esta acao."
    )


def _build_script_action(message: str, normalized_text: str) -> dict[str, Any] | None:
    direct_run_terms = (
        "execute",
        "executar",
        "rode",
        "rodar",
        "roda",
        "run",
    )
    pasted_instruction_markers = (
        "nao tenho capacidade",
        "nao consigo executar",
        "fornecer os scripts",
        "copie execute",
        "cole o resultado",
    )
    if not any(term in normalized_text for term in direct_run_terms):
        return None
    if any(marker in normalized_text for marker in pasted_instruction_markers):
        return None

    extracted = _extract_script(message)
    if not extracted:
        return None

    shell_hint, script = extracted
    shell = _infer_shell(shell_hint, script)
    high_risk = _has_high_risk_content(script)
    return {
        "type": "computer_action",
        "action_id": SCRIPT_EXECUTION.id,
        "name": SCRIPT_EXECUTION.name,
        "description": f"{SCRIPT_EXECUTION.description} Preview: {_script_preview(script)}",
        "risk_level": "high" if high_risk else SCRIPT_EXECUTION.risk_level,
        "requires_confirmation": True,
        "arguments": {
            "shell": shell,
            "script": script,
            "timeout_seconds": 30,
            "allow_high_risk": False,
        },
    }


def _extract_script(message: str) -> tuple[str, str] | None:
    code_block = re.search(
        r"```(?P<lang>[a-zA-Z0-9_+-]*)\s*\n(?P<script>.*?)```",
        message,
        flags=re.DOTALL,
    )
    if code_block:
        script = code_block.group("script").strip()
        if script:
            return code_block.group("lang").strip(), script

    inline = re.search(r"`(?P<script>[^`]{3,2000})`", message, flags=re.DOTALL)
    if inline:
        script = inline.group("script").strip()
        if _looks_like_shell_script(script):
            return "", script

    colon_match = re.search(
        r"(?:execute|executar|rode|rodar|roda|run)\s+(?:este|esse|o|a)?\s*"
        r"(?:script|comando|powershell|shell|bash)?\s*:\s*(?P<script>.+)$",
        message,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if colon_match:
        script = colon_match.group("script").strip()
        if _looks_like_shell_script(script):
            return "", script

    return None


def _looks_like_shell_script(script: str) -> bool:
    lowered = script.strip().lower()
    if "\n" in lowered and len(lowered) >= 8:
        return True
    shell_terms = (
        "get-",
        "select-object",
        "where-object",
        "write-output",
        "ipconfig",
        "ping ",
        "curl ",
        "df ",
        "ps ",
        "ls ",
        "dir ",
        "echo ",
        "$",
        "|",
    )
    return any(term in lowered for term in shell_terms)


def _infer_shell(shell_hint: str, script: str) -> str:
    hint = shell_hint.strip().lower()
    if hint in {"powershell", "ps1", "ps", "pwsh"}:
        return "powershell" if hint != "pwsh" else "pwsh"
    if hint in {"cmd", "bat", "batch"}:
        return "cmd"
    if hint in {"bash", "shell", "sh", "zsh"}:
        return "bash" if hint == "shell" else hint

    lowered = script.lower()
    powershell_terms = (
        "get-",
        "select-object",
        "where-object",
        "write-output",
        "$_.",
        "$env:",
    )
    if platform.system().lower() == "windows" or any(term in lowered for term in powershell_terms):
        return "powershell"
    return "bash"


def _script_preview(script: str, limit: int = 120) -> str:
    clean = re.sub(r"\s+", " ", script).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _has_high_risk_content(script: str) -> bool:
    lowered = script.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in _HIGH_RISK_PATTERNS)


def _contains_term(text: str, term: str) -> bool:
    if " " in term:
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}\b", text))


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).strip()
