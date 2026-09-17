"""Atalhos: encontrar no banco, registrar o uso e descobrir o comando.

O backend nunca abre nada. Ele reconhece o pedido, encontra o atalho no banco e
devolve uma `LaunchAction` para a interface executar - so ela tem acesso ao
desktop do usuario. Quando o alvo pedido nao tem atalho cadastrado, o modulo
propoe o cadastro em vez de falhar em silencio.

O reconhecimento por texto fica em `launcher_intent_service`; aqui fica o que
precisa de banco, sistema operacional ou modelo.
"""

import asyncio
import os
import re
import subprocess
import sys
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .user_llm_config_service import runtime_settings
from ..core.database import ShortcutLaunchLogModel, ShortcutModel
from ..models.schemas import LaunchAction, ShortcutType

# A deteccao por texto mora em `launcher_intent_service`, sem banco nem
# credenciais. Os nomes publicos sao reexportados para quem ja importa daqui.
from .launcher_intent_service import (  # noqa: F401
    _browser_from_description,
    _fold,
    _normalize,
    _trim_quotes,
    build_auto_registration_from_launch,
    build_project_open_action,
    build_registration_context,
    build_shortcut_registration_action,
    detect_launch_keywords,
    detect_registration_keywords,
)

_WINDOWS_APP_ALIASES: dict[str, list[str]] = {
    "bloco de notas": ["notepad.exe"],
    "notepad": ["notepad.exe"],
    "notepad plus plus": ["notepad++.exe"],
    "notepad++": ["notepad++.exe"],
    "calculadora": ["calc.exe"],
    "calculator": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "microsoft paint": ["mspaint.exe"],
    "explorador": ["explorer.exe"],
    "explorador de arquivos": ["explorer.exe"],
    "windows explorer": ["explorer.exe"],
    "prompt de comando": ["cmd.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
}

_COMMON_WINDOWS_PATHS: dict[str, list[str]] = {
    "notepad.exe": [
        r"%WINDIR%\System32\notepad.exe",
        r"%WINDIR%\notepad.exe",
    ],
    "notepad++.exe": [
        r"%ProgramFiles%\Notepad++\notepad++.exe",
        r"%ProgramFiles(x86)%\Notepad++\notepad++.exe",
        r"%LOCALAPPDATA%\Programs\Notepad++\notepad++.exe",
    ],
    "calc.exe": [r"%WINDIR%\System32\calc.exe"],
    "mspaint.exe": [r"%WINDIR%\System32\mspaint.exe"],
    "explorer.exe": [r"%WINDIR%\explorer.exe"],
    "cmd.exe": [r"%WINDIR%\System32\cmd.exe"],
    "powershell.exe": [
        r"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe",
    ],
}


async def find_shortcut_in_message(
    message: str, tutor_id: str, db: AsyncSession
) -> Optional[ShortcutModel]:
    """
    Tries to match any shortcut name or alias against the user message.
    Returns the best match or None.
    """
    if not detect_launch_keywords(message):
        return None

    normalized_msg = _normalize(message)

    result = await db.execute(
        select(ShortcutModel).where(ShortcutModel.tutor_id == tutor_id)
    )
    shortcuts = result.scalars().all()

    best: Optional[ShortcutModel] = None
    best_len = 0

    for sc in shortcuts:
        candidates = [sc.name] + (sc.aliases or [])
        for candidate in candidates:
            norm = _normalize(candidate)
            if norm and norm in normalized_msg and len(norm) > best_len:
                best = sc
                best_len = len(norm)

    return best


async def record_launch(
    shortcut_id: str,
    db: AsyncSession,
    *,
    status: str = "executed",
    source: str = "interface",
    platform: str | None = None,
    request: dict | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> ShortcutLaunchLogModel | None:
    """Records an app/URL launch attempt and updates shortcut counters on success."""
    from datetime import datetime, timezone

    sc = await db.get(ShortcutModel, shortcut_id)
    if not sc:
        return None

    launched_at = datetime.now(timezone.utc)
    if status == "executed":
        sc.use_count = (sc.use_count or 0) + 1
        sc.last_used_at = launched_at

    log = ShortcutLaunchLogModel(
        tutor_id=sc.tutor_id,
        shortcut_id=sc.id,
        shortcut_name=sc.name,
        target_type=sc.type,
        target=sc.target,
        status=status,
        source=source or "interface",
        platform=platform,
        request=request or {},
        result=result or {},
        error=error,
        launched_at=launched_at,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


def build_launch_action(sc: ShortcutModel) -> LaunchAction:
    """Converte um atalho do banco na acao que a interface executa."""
    return LaunchAction(
        shortcut_id=sc.id,
        name=sc.name,
        target=sc.target,
        target_type=ShortcutType(sc.type),
        browser=_browser_from_description(sc.description or "") if sc.type == "url" else "",
    )


def build_launch_context(sc: ShortcutModel) -> str:
    """Extra context injected into the system prompt when a launch is detected."""
    kind = "pagina" if sc.type == "url" else "aplicativo"
    return (
        f"\n\n[ACAO DETECTADA] O usuario quer abrir o {kind} '{sc.name}'. "
        f"Confirme de forma natural e breve que voce esta abrindo. "
        f"Nao mencione caminhos, URLs ou comandos tecnicos."
    )


async def _where_command(name: str) -> str | None:
    """Try to resolve an executable path using the Windows 'where' command."""
    if sys.platform != "win32":
        return None
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["where", name],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
            for line in lines:
                low = line.lower()
                if any(low.endswith(ext) for ext in (".exe", ".cmd", ".bat", ".ps1", ".lnk")):
                    return line
            if lines:
                return lines[0]
    except Exception:
        pass
    return None


def _clean_resolved_target(raw: str) -> str:
    return os.path.expandvars(raw.strip().strip("\"'` "))


def _existing_windows_path(target: str) -> str | None:
    if sys.platform != "win32":
        return None
    cleaned = _clean_resolved_target(target)
    if not cleaned or not re.search(r"[\\/]", cleaned):
        return None
    return cleaned if os.path.exists(cleaned) else None


def _known_windows_path(name: str) -> str | None:
    if sys.platform != "win32":
        return None
    for template in _COMMON_WINDOWS_PATHS.get(name.lower(), []):
        candidate = _clean_resolved_target(template)
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _windows_app_path(name: str) -> str | None:
    """Resolve executables registered in Windows App Paths."""
    if sys.platform != "win32":
        return None
    if re.search(r"[\\/]", name):
        return _existing_windows_path(name)

    try:
        import winreg
    except Exception:
        return None

    exe_name = name.strip().strip("\"'")
    if not exe_name:
        return None
    if not exe_name.lower().endswith((".exe", ".cmd", ".bat", ".ps1", ".lnk")):
        exe_name = f"{exe_name}.exe"

    roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
        ),
    )
    for hive, base in roots:
        try:
            with winreg.OpenKey(hive, rf"{base}\{exe_name}") as key:
                target, _ = winreg.QueryValueEx(key, "")
        except Exception:
            continue
        target = _clean_resolved_target(str(target))
        if target:
            return target
    return None


def _launch_command_candidates(name: str) -> list[str]:
    raw = _trim_quotes(name)
    folded = _fold(raw)
    spaced = re.sub(r"\s+", " ", folded).strip()
    normalized = re.sub(r"[^a-z0-9.+_-]+", " ", folded).strip()
    compact = re.sub(r"[^a-z0-9.+_-]+", "", folded)

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = _trim_quotes(value)
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(cleaned)
        if not re.search(r"[\\/]", cleaned) and not key.endswith(
            (".exe", ".cmd", ".bat", ".ps1", ".lnk")
        ):
            exe_key = f"{key}.exe"
            if exe_key not in seen:
                seen.add(exe_key)
                candidates.append(f"{cleaned}.exe")

    for value in (raw, spaced, normalized, compact):
        add(value)
    for key in (spaced, normalized, compact):
        for alias in _WINDOWS_APP_ALIASES.get(key, []):
            add(alias)

    return candidates


async def _llm_suggest_command(name: str) -> str | None:
    """Ask the active LLM for the Windows executable to open an app by name."""
    from .llm_service import dispatch_single
    from .llm_status_service import get_available_llms

    settings = runtime_settings
    available = set(await get_available_llms())
    active = [llm for llm in settings.active_llms if llm in available]
    if not active:
        return None

    prompt = (
        f"What is the exact Windows executable filename or full path to open '{name}'? "
        f"Reply with ONLY the command (examples: 'code.exe', 'notepad.exe', "
        f"'C:\\\\Program Files\\\\App\\\\app.exe'). "
        f"If unknown, reply exactly: UNKNOWN"
    )
    system = "You are a Windows expert. Reply with just the executable name or full path, no explanation."

    resp = await dispatch_single(active[0], prompt, [], system)
    if resp.is_error:
        return None

    raw = resp.content.strip().strip("\"'` ")
    if not raw or "UNKNOWN" in raw.upper() or len(raw) > 260:
        return None

    low = raw.lower()
    # Full path with separators — trust the LLM
    if "\\" in raw or "/" in raw:
        return raw

    # Short name (with or without extension) — always verify via 'where'
    if re.match(r"^[a-zA-Z0-9_.-]{2,80}$", raw):
        # Try the name as-is, then without any extension
        without_ext = re.sub(r"\.(exe|cmd|bat|ps1|lnk)$", "", low, flags=re.IGNORECASE)
        for candidate in dict.fromkeys([raw, without_ext]):  # preserve order, dedupe
            path = await _where_command(candidate)
            if path:
                return path

    return None


async def suggest_launch_command(name: str) -> str | None:
    """
    Find the Windows executable or path for an app by name.
    Strategy: aliases/common paths, 'where', Windows App Paths, then LLM.
    """
    name = name.strip()
    if not name:
        return None

    for candidate in _launch_command_candidates(name):
        path = _existing_windows_path(candidate)
        if path:
            return path
        path = _known_windows_path(candidate)
        if path:
            return path
        path = await _where_command(candidate)
        if path:
            return path
        path = _windows_app_path(candidate)
        if path:
            return path

    return await _llm_suggest_command(name)
