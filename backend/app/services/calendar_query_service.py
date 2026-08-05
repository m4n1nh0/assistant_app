from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Literal

import pytz
from pydantic import BaseModel, Field, ValidationError

from ..core.database import AsyncSessionLocal, ConfigModel, scoped_config_key
from ..models.schemas import CalendarEvent, Message
from . import langchain_agent_service
from .calendar_service import fetch_account_events_with_errors
from .llm_routing_service import pick_auto_llm


class CalendarQueryPlan(BaseModel):
    type: Literal["calendar_query"] = "calendar_query"
    start_time: datetime
    end_time: datetime
    timezone: str = "America/Sao_Paulo"
    provider: Literal["all", "google", "microsoft"] = "all"
    search_text: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=10, ge=1, le=25)
    interpreted_by: str = "fallback"


class CalendarQueryResult(BaseModel):
    events: list[CalendarEvent] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    connected_accounts: int = 0


_CREATE_RE = re.compile(
    r"\b(?:agende|agendar|marque|marcar|crie|criar|adicione|adicionar|"
    r"inclua|incluir|coloque|colocar)\b"
)
_CALENDAR_RE = re.compile(
    r"\b(?:agenda|calendario|calendar|compromissos?|eventos?|reunioes?|"
    r"reuniao|horarios?|programacao)\b"
)
_QUERY_RE = re.compile(
    r"\b(?:qual|quais|quando|o que|tenho|tem|mostre|mostrar|liste|listar|"
    r"consulte|consultar|veja|ver|proximo|proxima|livre|disponivel)\b"
)
_TECHNICAL_RE = re.compile(
    r"\b(?:oauth|escopo|credencial|client id|client secret|api|callback|"
    r"configurar|configuracao)\b"
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


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.lower())
    return "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )


def _timezone(name: str):
    try:
        return pytz.timezone(name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("America/Sao_Paulo")


def _local_now(timezone_name: str, now: datetime | None = None) -> datetime:
    tz = _timezone(timezone_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return tz.localize(now)
    return now.astimezone(tz)


def is_calendar_query_candidate(message: str) -> bool:
    normalized = _normalize(message).strip()
    if not normalized or _CREATE_RE.search(normalized):
        return False
    if _TECHNICAL_RE.search(normalized):
        return False
    if re.search(
        r"\b(?:o que tenho|estou livre|estou disponivel|meus compromissos|"
        r"minha agenda|proxima reuniao|proximo evento)\b",
        normalized,
    ):
        return True
    return bool(_CALENDAR_RE.search(normalized) and _QUERY_RE.search(normalized))


def _is_calendar_follow_up(message: str, history: list[Message]) -> bool:
    normalized = _normalize(message).strip()
    if not re.search(
        r"\b(?:e|hoje|amanha|semana|segunda|terca|quarta|quinta|sexta|"
        r"sabado|domingo|depois|antes|horas?)\b",
        normalized,
    ):
        return False
    return any(
        item.role == "user" and is_calendar_query_candidate(item.content)
        for item in history[-4:]
    )


def _day_bounds(day: date, timezone_name: str) -> tuple[datetime, datetime]:
    tz = _timezone(timezone_name)
    start = tz.localize(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def _numeric_day(text: str, today: date) -> date | None:
    iso = re.search(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", text)
    if iso:
        try:
            return date(*map(int, iso.groups()))
        except ValueError:
            return None
    numeric = re.search(
        r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?!\d)",
        text,
    )
    if not numeric:
        return None
    day, month, year = numeric.groups()
    parsed_year = int(year) if year else today.year
    if parsed_year < 100:
        parsed_year += 2000
    try:
        return date(parsed_year, int(month), int(day))
    except ValueError:
        return None


def _explicit_clock(text: str) -> tuple[int, int] | None:
    match = re.search(
        r"\b(?:depois\s+d(?:as?|e)|a partir d(?:as?|e)|(?:a|as|pelas?))\s*"
        r"(\d{1,2})(?:[:h](\d{2}))?\s*(?:h|horas?)?\b",
        text,
    )
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def build_fallback_calendar_query(
    message: str,
    *,
    timezone_name: str = "America/Sao_Paulo",
    now: datetime | None = None,
) -> CalendarQueryPlan | None:
    if not is_calendar_query_candidate(message):
        return None

    normalized = _normalize(message)
    local_now = _local_now(timezone_name, now)
    today = local_now.date()
    start: datetime
    end: datetime

    if "depois de amanha" in normalized:
        start, end = _day_bounds(today + timedelta(days=2), timezone_name)
    elif re.search(r"\bamanha\b", normalized):
        start, end = _day_bounds(today + timedelta(days=1), timezone_name)
    elif re.search(r"\bhoje\b", normalized):
        start, end = _day_bounds(today, timezone_name)
    elif re.search(r"\b(?:proxima semana|semana que vem)\b", normalized):
        next_monday = today + timedelta(days=(7 - today.weekday()))
        start, _ = _day_bounds(next_monday, timezone_name)
        end = start + timedelta(days=7)
    elif re.search(r"\b(?:esta semana|semana atual)\b", normalized):
        start, _ = _day_bounds(today, timezone_name)
        end = start + timedelta(days=(7 - today.weekday()))
    else:
        explicit_day = _numeric_day(normalized, today)
        weekday = re.search(
            r"\b(segunda(?:-feira)?|terca(?:-feira)?|quarta(?:-feira)?|"
            r"quinta(?:-feira)?|sexta(?:-feira)?|sabado|domingo)\b",
            normalized,
        )
        next_days = re.search(r"\bproximos?\s+(\d{1,2})\s+dias?\b", normalized)
        if explicit_day:
            start, end = _day_bounds(explicit_day, timezone_name)
        elif weekday:
            target = _WEEKDAYS[weekday.group(1)]
            day = today + timedelta(days=(target - today.weekday()) % 7)
            start, end = _day_bounds(day, timezone_name)
        elif next_days:
            start = local_now
            end = start + timedelta(days=min(int(next_days.group(1)), 31))
        else:
            start = local_now
            end = start + timedelta(days=7)

    clock = _explicit_clock(normalized)
    if clock:
        tz = _timezone(timezone_name)
        clock_start = tz.localize(
            datetime.combine(start.astimezone(tz).date(), time(*clock))
        )
        start = clock_start
        if re.search(r"\b(?:depois|a partir)\b", normalized):
            _, end = _day_bounds(clock_start.date(), timezone_name)
        else:
            end = start + timedelta(hours=1)

    provider: Literal["all", "google", "microsoft"] = "all"
    if re.search(r"\bgoogle\b", normalized):
        provider = "google"
    elif re.search(r"\b(?:microsoft|outlook|teams)\b", normalized):
        provider = "microsoft"

    singular_next = bool(
        re.search(r"\bproxim[oa]\s+(?:reuniao|evento|compromisso)\b", normalized)
    )
    if singular_next and not re.search(
        r"\b(?:hoje|amanha|semana|segunda|terca|quarta|quinta|sexta|"
        r"sabado|domingo)\b",
        normalized,
    ):
        start = local_now
        end = start + timedelta(days=31)
    return CalendarQueryPlan(
        start_time=start,
        end_time=end,
        timezone=timezone_name,
        provider=provider,
        limit=1 if singular_next else 10,
    )


def _json_object(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _validated_ai_plan(
    payload: dict,
    *,
    timezone_name: str,
    interpreter: str,
) -> CalendarQueryPlan | None:
    if str(payload.get("intent", "")).lower() != "calendar_query":
        return None
    provider = str(payload.get("provider") or "all").lower()
    if provider in {"outlook", "teams"}:
        provider = "microsoft"
    if provider not in {"all", "google", "microsoft"}:
        provider = "all"
    try:
        plan = CalendarQueryPlan.model_validate({
            "start_time": payload.get("start_time"),
            "end_time": payload.get("end_time"),
            "timezone": timezone_name,
            "provider": provider,
            "search_text": payload.get("search_text") or None,
            "limit": payload.get("limit") or 10,
            "interpreted_by": interpreter,
        })
    except (ValidationError, ValueError, TypeError):
        return None

    tz = _timezone(timezone_name)
    start = plan.start_time
    end = plan.end_time
    start = tz.localize(start) if start.tzinfo is None else start.astimezone(tz)
    end = tz.localize(end) if end.tzinfo is None else end.astimezone(tz)
    if end <= start:
        return None
    if end - start > timedelta(days=31):
        end = start + timedelta(days=31)
    return plan.model_copy(update={"start_time": start, "end_time": end})


def _interpreter_prompt(now: datetime, timezone_name: str) -> str:
    return f"""Você interpreta pedidos de leitura da agenda pessoal.
Data e hora local atual: {now.isoformat()}
Fuso horário: {timezone_name}

Retorne somente um objeto JSON, sem Markdown, com este formato:
{{"intent":"calendar_query|none","start_time":"RFC3339|null","end_time":"RFC3339|null","provider":"all|google|microsoft","search_text":null,"limit":10}}

Regras:
- calendar_query significa consultar eventos, compromissos, reuniões ou disponibilidade.
- Pedidos para criar, editar, excluir ou configurar calendários retornam intent none.
- end_time é exclusivo e deve ser posterior a start_time.
- "hoje" e "amanhã" representam o dia inteiro no fuso informado.
- "próximo compromisso" começa agora, procura por até 31 dias e usa limit 1.
- Sem período explícito, use agora até sete dias à frente.
- provider é all, exceto quando Google, Outlook, Teams ou Microsoft forem citados.
- search_text só recebe um título, pessoa ou termo que o usuário pediu para localizar.
- Não invente eventos e não inclua qualquer explicação fora do JSON.
"""


async def interpret_calendar_query(
    message: str,
    *,
    history: list[Message],
    timezone_name: str,
    requested_llm: str | None,
    active_llms: list[str],
    now: datetime | None = None,
) -> CalendarQueryPlan | None:
    direct_candidate = is_calendar_query_candidate(message)
    contextual_candidate = _is_calendar_follow_up(message, history)
    if not direct_candidate and not contextual_candidate:
        return None

    local_now = _local_now(timezone_name, now)
    provider = requested_llm if requested_llm in active_llms else ""
    if not provider and active_llms:
        provider = await pick_auto_llm(active_llms)

    if provider:
        try:
            user_history = [
                item for item in history[-8:] if item.role == "user"
            ][-4:]
            response = await asyncio.wait_for(
                langchain_agent_service.dispatch_single(
                    provider,
                    message,
                    user_history,
                    _interpreter_prompt(local_now, timezone_name),
                ),
                timeout=25,
            )
            if not response.is_error:
                payload = _json_object(response.content)
                if payload:
                    if str(payload.get("intent", "")).lower() == "none":
                        return None
                    plan = _validated_ai_plan(
                        payload,
                        timezone_name=timezone_name,
                        interpreter=provider,
                    )
                    if plan:
                        return plan
        except Exception:
            pass

    return build_fallback_calendar_query(
        message if direct_candidate else f"Minha agenda: {message}",
        timezone_name=timezone_name,
        now=local_now,
    )


def _json_value(row: ConfigModel | None, fallback):
    if row is None or not row.value:
        return fallback
    try:
        return json.loads(row.value)
    except Exception:
        return fallback


def _account_items(value) -> list[dict]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = value.get("accounts", [])
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _dedupe_accounts(accounts: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for account in accounts:
        account_id = str(account.get("id") or "")
        if not account_id or account_id in seen or not account.get("refresh_token"):
            continue
        seen.add(account_id)
        result.append(account)
    return result


async def _load_user_accounts(user_id: str) -> tuple[list[dict], list[dict]]:
    async with AsyncSessionLocal() as db:
        google = _account_items(_json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_google_accounts"),
            ),
            {"accounts": []},
        ))
        microsoft = _account_items(_json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_microsoft_accounts"),
            ),
            {"accounts": []},
        ))

        google_legacy = _json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_google"),
            ),
            {},
        )
        if google_legacy.get("refresh_token"):
            google.append({
                "id": "google_legacy",
                "label": google_legacy.get("label") or "Google Calendar",
                **google_legacy,
            })

        microsoft_legacy = _json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_microsoft"),
            ),
            {},
        )
        if microsoft_legacy.get("refresh_token"):
            microsoft.append({
                "id": "microsoft_legacy",
                "label": microsoft_legacy.get("label") or "Microsoft Calendar",
                **microsoft_legacy,
            })

    return _dedupe_accounts(google), _dedupe_accounts(microsoft)


async def execute_calendar_query(
    user_id: str,
    plan: CalendarQueryPlan,
) -> CalendarQueryResult:
    google, microsoft = await _load_user_accounts(user_id)
    if plan.provider == "google":
        microsoft = []
    elif plan.provider == "microsoft":
        google = []

    account_count = len(google) + len(microsoft)
    if not account_count:
        return CalendarQueryResult(connected_accounts=0)

    events, errors = await fetch_account_events_with_errors(
        google,
        microsoft,
        start_time=plan.start_time,
        end_time=plan.end_time,
        max_results=max(25, plan.limit),
    )

    tz = _timezone(plan.timezone)
    range_start = (
        tz.localize(plan.start_time)
        if plan.start_time.tzinfo is None
        else plan.start_time
    )
    range_end = (
        tz.localize(plan.end_time)
        if plan.end_time.tzinfo is None
        else plan.end_time
    )
    events = [
        event
        for event in events
        if event.start_time < range_end
        and (event.end_time or event.start_time) >= range_start
    ]

    normalized_search = _normalize(plan.search_text or "").strip()
    if normalized_search:
        events = [
            event
            for event in events
            if normalized_search in _normalize(
                f"{event.title} {event.description or ''}"
            )
        ]

    return CalendarQueryResult(
        events=events[:plan.limit],
        errors=errors,
        connected_accounts=account_count,
    )


def _period_label(plan: CalendarQueryPlan) -> str:
    tz = _timezone(plan.timezone)
    start = plan.start_time.astimezone(tz)
    end = plan.end_time.astimezone(tz)
    if start.time() == time.min and end.time() == time.min:
        if end.date() == start.date() + timedelta(days=1):
            return f"em {start:%d/%m/%Y}"
        return f"de {start:%d/%m/%Y} a {(end - timedelta(days=1)):%d/%m/%Y}"
    if start.date() == end.date():
        return f"em {start:%d/%m/%Y}, das {start:%H:%M} às {end:%H:%M}"
    return f"de {start:%d/%m/%Y %H:%M} a {end:%d/%m/%Y %H:%M}"


def format_calendar_query_response(
    plan: CalendarQueryPlan,
    result: CalendarQueryResult,
) -> str:
    period = _period_label(plan)
    if result.connected_accounts == 0:
        provider = {
            "google": "Google Calendar",
            "microsoft": "Microsoft Outlook",
            "all": "calendário",
        }[plan.provider]
        return f"Não encontrei uma conta de {provider} conectada ao seu usuário."

    if not result.events:
        if result.errors:
            return (
                f"Não consegui consultar sua agenda {period}. "
                "Verifique a conexão da conta em Configurações > Agendas."
            )
        suffix = f" com o termo “{plan.search_text}”" if plan.search_text else ""
        return f"Você não tem eventos{suffix} {period}."

    tz = _timezone(plan.timezone)
    lines = [f"Encontrei {len(result.events)} evento(s) {period}:"]
    source_labels = {
        "google": "Google",
        "outlook": "Outlook",
        "teams": "Teams",
    }
    for event in result.events:
        start = event.start_time.astimezone(tz)
        end = event.end_time.astimezone(tz) if event.end_time else None
        title = re.sub(r"\s+", " ", event.title).strip()[:200]
        title = re.sub(r"([\\`*_{}\[\]()#+.!|>])", r"\\\1", title)
        when = f"{start:%d/%m %H:%M}"
        if end:
            when += f"–{end:%H:%M}"
        source = source_labels.get(event.source, event.source.title())
        lines.append(f"- **{when}** — {title} ({source})")
    if result.errors:
        lines.append("\nAlgumas contas não puderam ser sincronizadas nesta consulta.")
    return "\n".join(lines)
