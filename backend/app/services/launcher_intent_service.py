"""Atalhos: reconhecer, no texto, o pedido de abrir ou cadastrar algo.

E a parte **pura** do launcher - expressao regular, normalizacao e montagem da
acao proposta. Nao toca banco, sistema operacional nem modelo, e por isso pode
ser carregada por qualquer processo: e o que o catalogo de ferramentas precisa,
e o tool-service nao deveria levar banco e credenciais junto so para ler texto.

Consultar o atalho cadastrado, registrar o uso e descobrir o comando no Windows
continuam em `launcher_service`, que reexporta os nomes publicos daqui.
"""

import json
import re
import unicodedata
from typing import Optional

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

# Verbos que, no vocabulario deste app, so aparecem quando o usuario pede um
# atalho.
_REGISTER_SHORTCUT_VERBS = r"cadastre|cadastrar|registre|registrar"
# Verbos de criacao em geral. "Crie um script para backup", "salve esse texto"
# e "adicione um lembrete" nao sao pedidos de atalho: eles so contam quando a
# frase diz que o objeto e um atalho/app ou traz um caminho ou uma URL.
_REGISTER_GENERIC_VERBS = (
    r"salve|salvar|crie|criar|adicione|adicionar|inclua|incluir"
)

_REGISTER_RE = re.compile(
    rf"\b({_REGISTER_SHORTCUT_VERBS}|{_REGISTER_GENERIC_VERBS})\b",
    re.IGNORECASE,
)

_REGISTER_SHORTCUT_VERB_RE = re.compile(
    rf"\b({_REGISTER_SHORTCUT_VERBS})\b",
    re.IGNORECASE,
)

# O que faz a frase falar de atalho, e nao de um arquivo qualquer que o
# usuario esta pedindo para a IA escrever.
_SHORTCUT_OBJECT_RE = re.compile(
    r"\b(atalho|atalhos|shortcut|shortcuts|app|apps|aplicativo|aplicativos|"
    r"programa|programas|executavel|executaveis)\b|\.(?:exe|lnk)\b",
    re.IGNORECASE,
)

# Endereco escrito por extenso. Deliberadamente mais restrito que `_URL_RE`,
# que aceita qualquer token com ponto: em "crie um script que leia
# config.json" o nome do arquivo nao pode virar destino de atalho.
_EXPLICIT_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)

# O `\b` no fim de cada palavra de ligacao e obrigatorio: sem ele o `a` da
# alternancia casava com a primeira letra de "atalho" e o nome do atalho saia
# comecando no meio da palavra ("crie um atalho para o Chrome" virava
# "talho para o Chrome").
_REGISTER_COMMAND_RE = re.compile(
    rf"\b(?:{_REGISTER_SHORTCUT_VERBS}|{_REGISTER_GENERIC_VERBS})\b"
    r"(?:\s+(?:um|uma|o|a|novo|nova|atalho|programa|app|"
    r"aplicativo|execucao|do|da|de|para)\b)*\s*",
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

def detect_launch_keywords(message: str) -> bool:
    """Diz se a mensagem parece um pedido de abrir app, site ou projeto."""
    return bool(_LAUNCH_RE.search(_fold(message)))


def detect_registration_keywords(message: str) -> bool:
    """Diz se a frase pede o cadastro de um atalho.

    "cadastre"/"registre" bastam, porque aqui so sao usados para isso. Verbo
    de criacao generico precisa de prova de que o objeto e um atalho: a
    palavra (atalho, app, programa) ou um destino concreto — caminho do
    Windows ou URL. Sem essa exigencia, "crie um script para backup
    automatico de arquivos" virava cadastro de atalho em vez de resposta no
    chat.
    """
    folded = _fold(message)
    if not _REGISTER_RE.search(folded):
        return False
    if _REGISTER_SHORTCUT_VERB_RE.search(folded):
        return True
    if _SHORTCUT_OBJECT_RE.search(folded):
        return True
    return bool(_EXPLICIT_URL_RE.search(folded) or _first_windows_path(message))


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
