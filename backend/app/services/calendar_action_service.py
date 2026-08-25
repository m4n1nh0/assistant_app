"""Detecta pedido de criar evento na conversa e monta a acao de calendario.

Trabalha so com regras, sem LLM: verbos de agendamento, data e hora em portugues.
Isso mantem o custo em zero e, principalmente, torna o comportamento previsivel -
criar evento e acao com efeito colateral, entao interpretar errado incomoda mais
do que nao interpretar.

Negacao explicita ("nao me agende...") e pergunta ("quando e...") sao descartadas
antes de qualquer coisa.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Any

import pytz


_CREATE_VERBS = (
    "agende",
    "agendar",
    "agenda",
    "marque",
    "marcar",
    "crie",
    "criar",
    "adicione",
    "adicionar",
    "inclua",
    "incluir",
    "coloque",
    "colocar",
)

_WEEKDAYS = {
    "segunda": 0,
    "segunda-feira": 0,
    "terca": 1,
    "terca-feira": 1,
    "quarta": 2,
    "quarta-feira": 2,
    "quinta": 3,
    "quinta-feira": 3,
    "sexta": 4,
    "sexta-feira": 4,
    "sabado": 5,
    "domingo": 6,
}

_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.lower())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _timezone(timezone_name: str):
    try:
        return pytz.timezone(timezone_name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("America/Sao_Paulo")


def _local_now(timezone_name: str, now: datetime | None) -> datetime:
    tz = _timezone(timezone_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return tz.localize(now)
    return now.astimezone(tz)


def _parse_date(text: str, today: date) -> date | None:
    iso_match = re.search(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", text)
    if iso_match:
        try:
            return date(*map(int, iso_match.groups()))
        except ValueError:
            return None

    numeric_match = re.search(
        r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?!\d)",
        text,
    )
    if numeric_match:
        day, month, year = numeric_match.groups()
        parsed_year = int(year) if year else today.year
        if parsed_year < 100:
            parsed_year += 2000
        try:
            parsed = date(parsed_year, int(month), int(day))
            if year is None and parsed < today:
                parsed = parsed.replace(year=parsed.year + 1)
            return parsed
        except ValueError:
            return None

    written_match = re.search(
        r"(?<!\d)(\d{1,2})\s+de\s+(" + "|".join(_MONTHS) + r")"
        r"(?:\s+de)?\s+(\d{4})(?!\d)",
        text,
    )
    if written_match:
        day, month_name, year = written_match.groups()
        try:
            return date(int(year), _MONTHS[month_name], int(day))
        except ValueError:
            return None

    if "depois de amanha" in text:
        return today + timedelta(days=2)
    if re.search(r"\bamanha\b", text):
        return today + timedelta(days=1)
    if re.search(r"\bhoje\b", text):
        return today

    weekday_match = re.search(
        r"\b(segunda(?:-feira)?|terca(?:-feira)?|quarta(?:-feira)?|"
        r"quinta(?:-feira)?|sexta(?:-feira)?|sabado|domingo)\b",
        text,
    )
    if weekday_match:
        target = _WEEKDAYS[weekday_match.group(1)]
        return today + timedelta(days=(target - today.weekday()) % 7)
    return None


def _valid_clock(hour: int, minute: int) -> bool:
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _parse_clock(raw_hour: str, raw_minute: str | None) -> time | None:
    hour = int(raw_hour)
    minute = int(raw_minute or 0)
    return time(hour, minute) if _valid_clock(hour, minute) else None


def _parse_times(text: str) -> tuple[time | None, time | None]:
    range_match = re.search(
        r"\b(?:das?|de)\s+(\d{1,2})(?:[:h](\d{2}))?\s*"
        r"(?:h\s*)?(?:as|ate|-)\s*(\d{1,2})(?:[:h](\d{2}))?\s*(?:h|horas?)?\b",
        text,
    )
    if range_match:
        start = _parse_clock(range_match.group(1), range_match.group(2))
        end = _parse_clock(range_match.group(3), range_match.group(4))
        return start, end

    patterns = (
        r"\b(?:as|a|para)\s+(\d{1,2})(?:[:h](\d{2}))?\s*(?:h|horas?)?\b",
        r"\b(\d{1,2})h(\d{2})?\b",
        r"\b(\d{1,2}):(\d{2})\b",
        r"\b(\d{1,2})\s+horas?\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 5):match.start()]
            if re.search(r"por\s+$", prefix):
                continue
            parsed = _parse_clock(match.group(1), match.group(2))
            if parsed:
                return parsed, None
    return None, None


def _duration(text: str) -> timedelta:
    match = re.search(r"\bpor\s+(\d+)\s*(minutos?|min|horas?|h)\b", text)
    if not match:
        return timedelta(hours=1)
    amount = int(match.group(1))
    if amount <= 0:
        return timedelta(hours=1)
    if match.group(2).startswith(("h", "hora")):
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def _provider(text: str) -> str:
    if re.search(r"\b(google|google calendar|google agenda)\b", text):
        return "google"
    if re.search(r"\b(microsoft|outlook|teams)\b", text):
        return "microsoft"
    return "auto"


def _invitation_title(request: str) -> str | None:
    teams = re.search(
        r"\breuni[aã]o\s+do\s+microsoft\s+teams\s*:\s*(.+?)"
        r"(?=\s*,\s*\d{1,2}\s+de\s+[a-zA-ZÃ-ÿ]+|"
        r"\s+link\s+da\s+reuni[aã]o\s*:|$)",
        request,
        flags=re.IGNORECASE,
    )
    if teams:
        return re.sub(r"\s+", " ", teams.group(1)).strip(" ,.;:-") or None

    invitation = re.search(
        r"\bconvidou\s+voc[eê]\s+para\s+(.+?)"
        r"(?=\s*,\s*\d{1,2}\s+de\s+[a-zA-ZÃ-ÿ]+|"
        r"\s+link\s+da\s+reuni[aã]o\s*:|$)",
        request,
        flags=re.IGNORECASE,
    )
    if not invitation:
        return None
    title = re.sub(
        r"^um(?:a)?\s+reuni[aã]o(?:\s+do\s+microsoft\s+teams)?\s*:\s*",
        "",
        invitation.group(1),
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", title).strip(" ,.;:-") or None


def _invitation_description(request: str) -> str | None:
    url_match = re.search(r"https?://[^\s'\"]+", request, flags=re.IGNORECASE)
    inviter_match = re.search(
        r"(?:^|[?.!]\s*)([^?.!]{2,120}?)\s+convidou\s+voc[eê]\b",
        request,
        flags=re.IGNORECASE,
    )
    details: list[str] = []
    if inviter_match:
        inviter = re.sub(r"\s+", " ", inviter_match.group(1)).strip(" ,.;:-")
        if inviter:
            details.append(f"Convite enviado por {inviter}.")
    if url_match:
        details.append(f"Link da reunião: {url_match.group(0).rstrip('.,;')}")
    return "\n".join(details) or None


def _clean_title(request: str) -> str:
    invitation_title = _invitation_title(request)
    if invitation_title:
        return invitation_title[:300]

    title = request.strip()
    title = re.sub(
        r"^\s*(?:por\s+favor[, ]+)?(?:eu\s+quero\s+que\s+voc[eê]\s+)?"
        r"(?:agende|agendar|agenda|marque|marcar|crie|criar|adicione|adicionar|"
        r"inclua|incluir|coloque|colocar)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    cleanup_patterns = (
        r"\b(?:depois\s+de\s+amanh[ãa]|amanh[ãa]|hoje)\b",
        r"\b(?:pr[oó]xim[ao]\s+)?(?:segunda|ter[cç]a|quarta|quinta|sexta)(?:-feira)?\b",
        r"\b(?:pr[oó]ximo\s+)?(?:s[áa]bado|domingo)\b",
        r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)",
        r"\b(?:no\s+)?dia\s+(?=\d)",
        r"(?<!\d)\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?!\d)",
        r"(?<!\d)\d{1,2}\s+de\s+(?:janeiro|fevereiro|mar[cç]o|abril|maio|"
        r"junho|julho|agosto|setembro|outubro|novembro|dezembro)"
        r"(?:\s+de\s+\d{4})?(?!\d)",
        r"\b(?:das?|de)\s+\d{1,2}(?:[:h]\d{2})?\s*(?:h\s*)?"
        r"(?:[àa]s|at[eé]|-)\s*\d{1,2}(?:[:h]\d{2})?\s*(?:h|horas?)?\b",
        r"\b(?:[àa]s|para)\s+\d{1,2}(?:[:h]\d{2})?\s*(?:h|horas?)?\b",
        r"\b\d{1,2}h\d{0,2}\b",
        r"\b\d{1,2}:\d{2}\b",
        r"\bpor\s+\d+\s*(?:minutos?|min|horas?|h)\b",
        r"\b(?:no|na|para\s+o|para\s+a)\s+(?:meu|minha\s+)?"
        r"(?:google\s+(?:calendar|agenda)|calendar\s+do\s+google|"
        r"outlook|microsoft|teams|agenda|calend[áa]rio)\b",
    )
    for pattern in cleanup_patterns:
        title = re.sub(pattern, " ", title, flags=re.IGNORECASE)
    title = re.sub(r"^\s*(?:um|uma|o|a)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(
        r"^\s*(?:evento|compromisso)\s+(?:chamado|intitulado)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s+", " ", title).strip(" ,.;:-")
    title = re.sub(r"https?://\S+", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" ,.;:-")
    title = re.sub(r"\s+(?:para|em|no|na)$", "", title, flags=re.IGNORECASE)
    return title[:300]


def build_calendar_create_action(
    request: str,
    *,
    timezone_name: str = "America/Sao_Paulo",
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Monta a acao de criacao de evento a partir do texto do usuario.

    Args:
        request: mensagem do usuario.
        timezone_name: fuso usado para resolver "amanha", "as 14h" e afins.
        now: instante de referencia; util em teste.

    Returns:
        O dicionario da acao pronto para a interface confirmar, ou `None` quando a
        mensagem nao e um pedido de agendamento.
    """
    normalized = _normalize(request).strip()
    if not normalized or normalized.startswith(("como ", "quando ", "qual ")):
        return None
    if re.search(
        r"\bnao\s+(?:me\s+)?(?:agende|marque|crie|adicione|inclua|coloque)\b",
        normalized,
    ):
        return None
    if not any(re.search(rf"\b{verb}\b", normalized) for verb in _CREATE_VERBS):
        return None

    local_now = _local_now(timezone_name, now)
    event_date = _parse_date(normalized, local_now.date())
    start_clock, end_clock = _parse_times(normalized)
    if event_date is None or start_clock is None:
        return None

    tz = _timezone(timezone_name)
    start_naive = datetime.combine(event_date, start_clock)
    try:
        start_time = tz.localize(start_naive, is_dst=None)
    except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
        start_time = tz.localize(start_naive, is_dst=False)

    if start_time <= local_now:
        weekday_mentioned = any(day in normalized for day in _WEEKDAYS)
        if weekday_mentioned and event_date == local_now.date():
            start_time += timedelta(days=7)
        else:
            return None

    if end_clock:
        end_naive = datetime.combine(start_time.date(), end_clock)
        try:
            end_time = tz.localize(end_naive, is_dst=None)
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
            end_time = tz.localize(end_naive, is_dst=False)
        if end_time <= start_time:
            end_time += timedelta(days=1)
    else:
        end_time = start_time + _duration(normalized)

    title = _clean_title(request)
    if not title:
        return None

    return {
        "type": "calendar_create",
        "title": title,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "timezone": (
            timezone_name
            if timezone_name in pytz.all_timezones_set
            else "America/Sao_Paulo"
        ),
        "provider": _provider(normalized),
        "description": _invitation_description(request),
        "location": None,
        "requires_confirmation": True,
    }
