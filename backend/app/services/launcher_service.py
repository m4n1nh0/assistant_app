import asyncio
import json
import os
import re
import subprocess
import sys
import unicodedata
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .user_llm_config_service import runtime_settings
from ..core.database import ShortcutLaunchLogModel, ShortcutModel
from ..models.schemas import LaunchAction, ShortcutRegistrationAction, ShortcutType

# Patterns that indicate the user wants to open/launch something.
_LAUNCH_RE = re.compile(
    r"\b(abre|abrir|abra|abrindo|lanca|lancar|"
    r"mostra|mostrar|exibe|exibir|"
    r"executa|executar|roda|rodar|inicia|iniciar|"
    r"navega\s+(?:para|pra)|vai\s+(?:para|pra)|"
    r"open|launch|start|run)\b",
    re.IGNORECASE,
)

_REGISTER_RE = re.compile(
    r"\b(cadastre|cadastrar|registre|registrar|salve|salvar|"
    r"crie|criar|adicione|adicionar|inclua|incluir)\b",
    re.IGNORECASE,
)

_REGISTER_COMMAND_RE = re.compile(
    r"\b(?:cadastre|cadastrar|registre|registrar|salve|salvar|"
    r"crie|criar|adicione|adicionar|inclua|incluir)\b"
    r"(?:\s+(?:um|uma|o|a|novo|nova|atalho|programa|app|"
    r"aplicativo|execucao|do|da|de|para))*\s*",
    re.IGNORECASE,
)

_PROJECT_TERMS_RE = re.compile(r"\b(projeto|project|repo|repositorio)\b", re.IGNORECASE)
_QUESTION_PROJECT_RE = re.compile(
    r"\b(algum|qualquer|nome\s+do\s+projeto|se\s+eu|se\s+te|disser|dizer)\b",
    re.IGNORECASE,
)

_IDE_PREPOSITIONS = r"no|na|com|pelo|pela|em|usando|via"


class _IdeSpec:
    """How one IDE is recognized in a message and stripped from the project name.

    `detect` decides whether the message asks for this IDE; `strip` removes every
    mention of it while extracting the project name. They differ when a name is
    ambiguous on its own — "code" only counts as VS Code right after a
    preposition ("no code"), otherwise it is ordinary prose.
    """

    def __init__(self, ide_id: str, label: str, detect: str, strip: str):
        self.ide_id = ide_id
        self.label = label
        self.detect = re.compile(detect, re.IGNORECASE)
        self.strip = strip


_IDE_SPECS: tuple[_IdeSpec, ...] = (
    _IdeSpec(
        ide_id="pycharm",
        label="PyCharm",
        detect=r"\bpy\s*charm\b",
        strip=r"py\s*charm",
    ),
    _IdeSpec(
        ide_id="vscode",
        label="VS Code",
        detect=(
            r"\b(?:vs\s*code|visual\s+studio\s+code)\b"
            rf"|\b(?:{_IDE_PREPOSITIONS})\s+code\b"
        ),
        strip=r"vs\s*code|visual\s+studio\s+code|code",
    ),
)


def _detect_ide(text: str) -> Optional[_IdeSpec]:
    """Returns the IDE mentioned earliest in the message, or None."""
    best: Optional[tuple[int, _IdeSpec]] = None
    for spec in _IDE_SPECS:
        match = spec.detect.search(text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), spec)
    return best[1] if best else None

_URL_RE = re.compile(
    r"\b((?:https?://|www\.)[^\s,;]+|"
    r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s,;]*)?)",
    re.IGNORECASE,
)

_WINDOWS_PATH_RE = re.compile(
    r"([a-z]:\\[^\n\r\"']+?(?:\.exe|\.lnk|\.bat|\.cmd|\.ps1)?)"
    r"(?=$|\s+(?:como|chamado|chamada|apelido|alias|para|pra|pro|com)\b|[,;])",
    re.IGNORECASE,
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


def detect_launch_keywords(message: str) -> bool:
    return bool(_LAUNCH_RE.search(_fold(message)))


def detect_registration_keywords(message: str) -> bool:
    return bool(_REGISTER_RE.search(_fold(message)))


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _normalize(text: str) -> str:
    folded = _fold(text).replace("++", " plus plus ")
    return re.sub(r"[^\w\s]", "", folded).strip()


def _trim_quotes(text: str) -> str:
    return text.strip().strip("\"'`").strip()


def _normalize_url(raw_url: str) -> str:
    url = raw_url.rstrip(".,;")
    if url.lower().startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def _first_url(text: str) -> tuple[str, tuple[int, int]] | None:
    match = _URL_RE.search(_fold(text))
    if not match:
        return None
    return _normalize_url(text[match.start(1):match.end(1)]), match.span(1)


def _first_windows_path(text: str) -> tuple[str, tuple[int, int]] | None:
    match = _WINDOWS_PATH_RE.search(text)
    if not match:
        return None
    return _trim_quotes(match.group(1)), match.span(1)


def _display_name_from_target(target: str) -> str:
    if not target:
        return ""
    url_match = re.match(r"https?://([^/]+)", target, re.IGNORECASE)
    if url_match:
        host = url_match.group(1).removeprefix("www.")
        return host.split(".")[0].replace("-", " ").title()
    file_name = target.replace("/", "\\").split("\\")[-1]
    name = re.sub(r"\.(exe|lnk|bat|cmd|ps1)$", "", file_name, flags=re.IGNORECASE)
    return name.strip() or target


def _clean_registration_name(text: str) -> str:
    cleaned = _trim_quotes(text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    folded = _fold(cleaned)
    for pattern in (
        r"^(?:como|chamado|chamada|nomeado|nomeada)\s+",
        r"^(?:para\s+)?(?:abrir|executar|rodar|iniciar)\s+",
        r"^(?:um|uma|o|a|novo|nova|atalho|programa|app|aplicativo)\s+",
    ):
        match = re.match(pattern, folded, re.IGNORECASE)
        if match:
            cleaned = cleaned[match.end():].strip()
            folded = _fold(cleaned)
    cleaned = re.sub(
        r"\s+para\s+(?:abrir|executar|rodar|iniciar)(?:\s+\w+){0,3}$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+(?:para|pra|pro|com|no|na|em|destino|caminho|url|link)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return _trim_quotes(cleaned).strip(" .,:;-")


def _aliases_for_name(name: str, query: str) -> list[str]:
    aliases: set[str] = set()
    for item in (name, query):
        cleaned = _clean_registration_name(item).lower()
        if len(cleaned) > 1:
            aliases.add(cleaned)
    return sorted(aliases)


def build_shortcut_registration_action(
    message: str,
) -> Optional[ShortcutRegistrationAction]:
    """
    Builds a client-side action to register an app/URL shortcut from chat.
    The interface resolves local apps because it has access to the desktop.
    """
    if not detect_registration_keywords(message):
        return None

    folded = _fold(message)
    command = _REGISTER_COMMAND_RE.search(folded)
    rest = message[command.end():].strip() if command else message.strip()
    if not rest:
        return None

    target = ""
    target_type = ShortcutType.app
    target_span: tuple[int, int] | None = None

    path = _first_windows_path(rest)
    if path:
        target, target_span = path
        target_type = ShortcutType.app
    else:
        url = _first_url(rest)
        if url:
            target, target_span = url
            target_type = ShortcutType.url

    name_part = rest
    if target_span:
        before = rest[:target_span[0]].strip(" ,;:-")
        after = rest[target_span[1]:].strip(" ,;:-")
        alias_match = re.search(
            r"\b(?:como|chamado|chamada|nomeado|nomeada)\s+(.+)$",
            _fold(after),
            re.IGNORECASE,
        )
        if before:
            name_part = before
        elif alias_match:
            name_part = after[alias_match.start(1):alias_match.end(1)]
        else:
            name_part = _display_name_from_target(target)

    name = _clean_registration_name(name_part) or _display_name_from_target(target)
    query = _clean_registration_name(name_part if not target else name_part or name)
    if not name and not target:
        return None

    return ShortcutRegistrationAction(
        name=name or query or _display_name_from_target(target),
        query=query or name,
        target=target,
        target_type=target_type,
        aliases=_aliases_for_name(name, query),
        description="Solicitado pelo chat.",
    )


def build_auto_registration_from_launch(
    message: str,
) -> Optional[ShortcutRegistrationAction]:
    """
    When the user says 'abra X' but X has no registered shortcut,
    return a registration action so the interface can discover and save it.
    Only fires when there's a clear, specific target (not vague phrases).
    """
    if not detect_launch_keywords(message):
        return None

    # Strip the launch verb to get the target phrase
    folded = _fold(message)
    launch_match = _LAUNCH_RE.search(folded)
    if not launch_match:
        return None
    rest = message[launch_match.end():].strip()
    # Remove leading filler words (articles/prepositions)
    rest = re.sub(
        r"^(?:o|a|os|as|um|uma|o\s+app|a\s+app|o\s+programa|a\s+pagina|o\s+site)\s+",
        "",
        rest,
        flags=re.IGNORECASE,
    ).strip()
    if not rest or len(rest) < 2:
        return None

    target = ""
    target_type = ShortcutType.app

    path = _first_windows_path(rest)
    if path:
        target, _ = path
        target_type = ShortcutType.app
    else:
        url = _first_url(rest)
        if url:
            target, _ = url
            target_type = ShortcutType.url

    name = _clean_registration_name(rest) or _display_name_from_target(target)
    if not name or len(name) < 2:
        return None

    # Reject overly generic words/phrases that aren't real app names
    _GENERIC = re.compile(
        r"^(janela|janelas|terminal|arquivo|arquivos|pasta|pastas|"
        r"isso|aquilo|algo|este|esse|esta|essa|tudo|nada|"
        r"uma?\s+janela|o\s+terminal|um?\s+arquivo)$",
        re.IGNORECASE,
    )
    if _GENERIC.match(_fold(name)):
        return None

    return ShortcutRegistrationAction(
        name=name,
        query=name,
        target=target,
        target_type=target_type,
        aliases=_aliases_for_name(name, name),
        description="Detectado automaticamente pelo chat.",
        open_after_register=True,
    )


def build_project_open_action(message: str) -> Optional[LaunchAction]:
    """
    Builds a client-side command to open a local project folder in an IDE.
    The interface resolves the project path because it can scan the desktop.
    """
    if not detect_launch_keywords(message):
        return None

    folded = _fold(message)
    ide = _detect_ide(folded)
    if ide is None:
        return None
    if _QUESTION_PROJECT_RE.search(folded):
        return None

    project_name = _extract_project_name_for_ide(message, ide)
    if not project_name:
        return None

    payload = json.dumps(
        {
            "version": 1,
            "platform": "desktop",
            "runner": "openProjectInIde",
            "ide": ide.ide_id,
            "project_query": project_name,
        },
        ensure_ascii=True,
    )
    return LaunchAction(
        type="open_project",
        shortcut_id="",
        name=f"{project_name} no {ide.label}",
        target=payload,
        target_type=ShortcutType.command,
    )


def _extract_project_name_for_ide(message: str, ide: _IdeSpec) -> str:
    text = re.sub(r"\s+", " ", _trim_quotes(message)).strip()
    folded = _fold(text)
    launch_match = _LAUNCH_RE.search(folded)
    if launch_match:
        text = text[launch_match.end() :].strip(" ,;:-")

    name = ide.strip
    patterns = (
        rf"(?:projeto|project|repo|repositorio)\s+(.+?)\s+"
        rf"(?:{_IDE_PREPOSITIONS})\s+(?:{name})\b",
        rf"(?:{_IDE_PREPOSITIONS})\s+(?:{name})\s+"
        rf"(?:o|a|um|uma)?\s*(?:projeto|project|repo|repositorio)?\s+(.+)$",
        rf"(?:{name})\s+"
        rf"(?:o|a|um|uma)?\s*(?:projeto|project|repo|repositorio)?\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _clean_project_name(match.group(1))

    cleaned = re.sub(
        rf"\b(?:{_IDE_PREPOSITIONS})\s+(?:{name})\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(rf"\b(?:{name})\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^(?:o|a|um|uma)?\s*(?:projeto|project|repo|repositorio)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return _clean_project_name(cleaned)


def _clean_project_name(raw: str) -> str:
    cleaned = _trim_quotes(raw)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(
        r"\s+(?:por favor|pfv|agora|pra mim|para mim)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.strip(" .,:;-")
    folded = _fold(cleaned)
    if len(cleaned) < 2:
        return ""
    if _QUESTION_PROJECT_RE.search(folded):
        return ""
    if folded in _NON_PROJECT_NAMES:
        return ""
    return cleaned


_NON_PROJECT_NAMES = {
    "projeto",
    "project",
    "repo",
    "repositorio",
    "pycharm",
    "py charm",
    "vscode",
    "vs code",
    "visual studio code",
    "code",
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
    return LaunchAction(
        shortcut_id=sc.id,
        name=sc.name,
        target=sc.target,
        target_type=ShortcutType(sc.type),
        browser=_browser_from_description(sc.description or "") if sc.type == "url" else "",
    )


def _browser_from_description(description: str) -> str:
    match = re.search(
        r"\[assistant:url_browser=([a-z0-9_-]+)\]",
        description or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    browser = match.group(1).strip().lower()
    return browser if browser in {"chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"} else ""


def build_launch_context(sc: ShortcutModel) -> str:
    """Extra context injected into the system prompt when a launch is detected."""
    kind = "pagina" if sc.type == "url" else "aplicativo"
    return (
        f"\n\n[ACAO DETECTADA] O usuario quer abrir o {kind} '{sc.name}'. "
        f"Confirme de forma natural e breve que voce esta abrindo. "
        f"Nao mencione caminhos, URLs ou comandos tecnicos."
    )


def build_registration_context(action: ShortcutRegistrationAction) -> str:
    """Extra context injected when a shortcut registration is detected."""
    kind = "pagina" if action.target_type == ShortcutType.url else "aplicativo"
    target_hint = " informado" if action.target else " encontrado no computador"
    return (
        f"\n\n[ACAO DETECTADA] O usuario quer cadastrar o {kind} "
        f"'{action.name}' para abertura futura pelo chat. "
        f"Confirme de forma natural e breve que voce esta cadastrando "
        f"o atalho usando o destino{target_hint}. "
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
