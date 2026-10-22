"""Integracao com Google Calendar e Microsoft Graph: OAuth, leitura e escrita.

Cada provedor entra por tres caminhos: montar a URL de consentimento, trocar o
codigo por tokens e usar o access token para ler ou criar evento. O que sai
daqui ja e `CalendarEvent`, entao o resto do backend nao sabe de qual provedor o
evento veio.

Uma conta pode ter varios calendarios conectados ao mesmo tempo - dai a
existencia das funcoes `..._account_events`, que trabalham sobre a lista de
contas do usuario em vez de uma configuracao unica.
"""

import asyncio
import base64
import hashlib
import json
import time
from urllib.parse import urlencode

import httpx
from datetime import date, datetime, timezone, timedelta
from typing import List, Optional
from loguru import logger

from ..core.config import get_settings
from ..models.schemas import CalendarEvent, CalendarConfig
from . import calendar_cache

settings = get_settings()

# `openid email` so serve para saber de quem e a conta: sem o e-mail, reconectar a mesma conta
# Google nao se distingue de conectar outra, e a lista enche de "Google Calendar" repetidos.
GOOGLE_CALENDAR_SCOPE = "openid email https://www.googleapis.com/auth/calendar.events"
MICROSOFT_CALENDAR_SCOPE = (
    "openid profile email offline_access User.Read Calendars.ReadWrite"
)


class MicrosoftAuthenticationError(RuntimeError):
    """Safe, user-facing Microsoft authentication failure."""


def microsoft_auth_error_message(error: str, description: str = "") -> str:
    """Traduz o erro da Microsoft em uma mensagem util para o usuario.

    Args:
        error: codigo devolvido pela API.
        description: descricao longa, quando vier.

    Returns:
        Texto em portugues explicando o que fazer, sem expor token ou URL interna.
    """
    combined = f"{error} {description}".lower()
    if "aadsts53003" in combined or "conditional access" in combined:
        return (
            "O acesso foi bloqueado por uma politica da organizacao Microsoft. "
            "Entre em contato com o administrador da sua instituicao."
        )
    if "aadsts65001" in combined or "admin consent" in combined:
        return (
            "A organizacao exige consentimento administrativo para esta integracao. "
            "Solicite a aprovacao do administrador Microsoft."
        )
    if "access_denied" in combined or "aadsts65004" in combined:
        return "A autorizacao Microsoft foi cancelada ou recusada."
    if "invalid_grant" in combined or "interaction_required" in combined:
        return "A sessao Microsoft expirou ou foi revogada. Reconecte a conta."
    return (
        "A Microsoft nao concluiu a autenticacao. Tente novamente ou consulte "
        "o administrador da sua organizacao."
    )


def get_google_auth_url(
    client_id: str,
    state: str | None = None,
    redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob",
) -> str:
    """Monta a URL de consentimento do Google Calendar."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent select_account",
    }
    if state:
        params["state"] = state
    qs = urlencode(params)
    return f"https://accounts.google.com/o/oauth2/auth?{qs}"


def google_email_from_id_token(id_token: str | None) -> str:
    """E-mail da conta Google a partir do `id_token` da troca de codigo.

    O token chega direto do Google, por TLS, na resposta do endpoint de tokens; por isso o
    conteudo e lido sem validar a assinatura. Serve so para rotular e reconhecer a conta.
    """
    try:
        payload = (id_token or "").split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return str(claims.get("email") or "").strip().lower()
    except Exception:
        return ""


async def exchange_google_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob",
) -> str:
    """Troca o codigo de autorizacao do Google pelo refresh token."""
    refresh, _email = await exchange_google_code_with_email(
        code, client_id, client_secret, redirect_uri)
    return refresh


async def exchange_google_code_with_email(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob",
) -> tuple[str, str]:
    """Troca o codigo pelo refresh token e devolve tambem o e-mail da conta ("" se nao vier)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    data = resp.json()
    if "error" in data:
        raise Exception(data.get("error_description", data["error"]))
    return data["refresh_token"], google_email_from_id_token(data.get("id_token"))


# Token de acesso por conta, ate perto de expirar. O provedor entrega um por hora; pedir outro a
# cada leitura era uma ida ao servidor de autenticacao so para repetir o que ja se tinha. Fica na
# memoria do processo e nunca no Redis: e credencial.
_TOKEN_SAFETY_SECONDS = 120
_tokens: dict[str, tuple[str, float]] = {}


def _token_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _cached_token(key: str) -> str | None:
    cached = _tokens.get(key)
    if cached and time.monotonic() < cached[1]:
        return cached[0]
    _tokens.pop(key, None)
    return None


def _remember_token(key: str, token: str, expires_in: object) -> None:
    try:
        lifetime = float(expires_in)
    except (TypeError, ValueError):
        lifetime = 3600.0
    ttl = lifetime - _TOKEN_SAFETY_SECONDS
    if ttl > 0:
        _tokens[key] = (token, time.monotonic() + ttl)


def clear_token_cache() -> None:
    """Esvazia os tokens guardados (testes)."""
    _tokens.clear()


class GoogleAuthError(Exception):
    """O Google recusou a autorizacao da conta (revogada, expirada ou credencial errada).

    Repetir nao adianta: so reconectar a conta resolve. Por isso a falha e lembrada, e o
    agendador deixa de bater no Google a cada ciclo para ouvir a mesma recusa.
    """


#: Erros do endpoint de token que significam "esta autorizacao morreu", e nao "tente de novo".
_GOOGLE_AUTH_ERRORS = {
    "invalid_grant": "a autorização expirou ou foi revogada",
    "invalid_client": "o Client ID ou o Client Secret não são aceitos",
    "unauthorized_client": "este Client ID não pode renovar o acesso",
}
#: De quanto em quanto tempo uma conta recusada tenta de novo (a pessoa pode ter reconectado
#: por outro caminho). Reconectar gera outro refresh token e, portanto, outra chave.
_AUTH_RETRY_SECONDS = 3600
_auth_failures: dict[str, tuple[float, str]] = {}


def google_auth_failure(account: dict) -> str | None:
    """Motivo da recusa recente do Google para esta conta, ou `None` se ela esta bem."""
    key = _token_key("google", account.get("client_id", ""), account.get("refresh_token", ""))
    failed = _auth_failures.get(key)
    if failed and time.monotonic() < failed[0]:
        return failed[1]
    _auth_failures.pop(key, None)
    return None


async def _get_google_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> str:
    key = _token_key("google", client_id, refresh_token)
    if (cached := _cached_token(key)) is not None:
        return cached
    failed = _auth_failures.get(key)
    if failed and time.monotonic() < failed[0]:
        raise GoogleAuthError(failed[1])
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
    data = resp.json()
    if "error" in data:
        reason = _GOOGLE_AUTH_ERRORS.get(str(data["error"]))
        detail = data.get("error_description", data["error"])
        if reason:
            message = f"Google recusou renovar o acesso: {reason} ({detail}). Reconecte a conta."
            _auth_failures[key] = (time.monotonic() + _AUTH_RETRY_SECONDS, message)
            logger.warning(f"Google Calendar: {message}")
            raise GoogleAuthError(message)
        raise Exception(detail)
    _remember_token(key, data["access_token"], data.get("expires_in"))
    return data["access_token"]


def _calendar_window(
    start_time: datetime | None,
    end_time: datetime | None,
) -> tuple[datetime, datetime]:
    start = start_time or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = end_time or (start + timedelta(days=7))
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return start, end


def _provider_datetime(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def fetch_google_events(
    config: CalendarConfig,
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_results: int = 25,
    raise_on_error: bool = False,
) -> List[CalendarEvent]:
    """Busca eventos de uma conta Google e devolve ja normalizados."""
    if not config.google_enabled or not config.google_refresh_token:
        return []
    try:
        token = await _get_google_access_token(
            config.google_client_id,
            config.google_client_secret,
            config.google_refresh_token,
        )
        range_start, range_end = _calendar_window(start_time, end_time)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": range_start.isoformat(),
                    "timeMax": range_end.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": str(max(1, min(max_results, 100))),
                },
            )
        data = resp.json()
        if "error" in data:
            raise Exception(data["error"]["message"])

        events = []
        for item in data.get("items", []):
            start_raw = item["start"].get("dateTime") or item["start"].get("date")
            end_raw   = item["end"].get("dateTime")   or item["end"].get("date")
            events.append(CalendarEvent(
                id=item["id"],
                title=item.get("summary", "Sem título"),
                start_time=_provider_datetime(start_raw),
                end_time=_provider_datetime(end_raw) if end_raw else None,
                source="google",
                meeting_url=item.get("hangoutLink") or _extract_meet(item.get("description", "")),
                description=item.get("description"),
            ))
        return events
    except Exception as e:
        # Recusa de autorizacao ja foi registrada quando aconteceu; repetir o log a cada ciclo
        # do agendador so enche o registro com a mesma linha.
        if not isinstance(e, GoogleAuthError):
            logger.error(f"Google Calendar error: {e}")
        if raise_on_error:
            raise RuntimeError(str(e)) from e
        return []


def _extract_meet(text: str) -> Optional[str]:
    import re
    m = re.search(r"https://meet\.google\.com/[^\s<>\"]+", text)
    return m.group(0) if m else None


def get_microsoft_auth_url(
    client_id: str,
    tenant_id: str = "common",
    state: str | None = None,
    redirect_uri: str = "https://login.microsoftonline.com/common/oauth2/nativeclient",
    code_challenge: str | None = None,
) -> str:
    """Monta a URL de consentimento da Microsoft (App Registration multitenant)."""
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": MICROSOFT_CALENDAR_SCOPE,
        "response_mode": "query",
        "prompt": "select_account",
    }
    if state:
        params["state"] = state
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    qs = urlencode(params)
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{qs}"


async def exchange_microsoft_code(
    code: str,
    client_id: str,
    client_secret: str,
    tenant_id: str = "common",
    redirect_uri: str = "https://login.microsoftonline.com/common/oauth2/nativeclient",
    code_verifier: str | None = None,
) -> dict:
    """Troca o codigo de autorizacao da Microsoft pelos tokens."""
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": MICROSOFT_CALENDAR_SCOPE,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data=payload,
        )
    data = resp.json()
    if "error" in data:
        raise MicrosoftAuthenticationError(microsoft_auth_error_message(
            str(data.get("error", "")), str(data.get("error_description", ""))
        ))
    if not data.get("refresh_token") or not data.get("access_token"):
        raise MicrosoftAuthenticationError(
            "A Microsoft nao retornou uma sessao persistente. Autorize novamente."
        )
    return data


async def fetch_microsoft_profile(access_token: str) -> dict:
    """Le o perfil da conta Microsoft, usado para rotular o calendario conectado."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
    data = response.json()
    if response.is_error or "error" in data:
        raise MicrosoftAuthenticationError(
            "A conta foi autorizada, mas o perfil Microsoft nao pode ser lido."
        )
    return {
        "microsoft_user_id": str(data.get("id") or ""),
        "display_name": str(data.get("displayName") or ""),
        "email": str(data.get("mail") or data.get("userPrincipalName") or ""),
    }


async def _get_ms_access_token(
    client_id: str, client_secret: str, tenant_id: str, refresh_token: str
) -> str:
    key = _token_key("microsoft", client_id, tenant_id, refresh_token)
    if (cached := _cached_token(key)) is not None:
        return cached
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "scope": MICROSOFT_CALENDAR_SCOPE,
            },
        )
    data = resp.json()
    if "error" in data:
        raise MicrosoftAuthenticationError(microsoft_auth_error_message(
            str(data.get("error", "")), str(data.get("error_description", ""))
        ))
    _remember_token(key, data["access_token"], data.get("expires_in"))
    return data["access_token"]


async def validate_microsoft_session(account: dict) -> None:
    """Checks whether a stored delegated session can still mint access tokens."""
    await _get_ms_access_token(
        account.get("client_id", ""),
        account.get("client_secret", ""),
        account.get("tenant_id", "common"),
        account.get("refresh_token", ""),
    )


async def fetch_microsoft_events(
    config: CalendarConfig,
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_results: int = 25,
    raise_on_error: bool = False,
) -> List[CalendarEvent]:
    """Busca eventos de uma conta Microsoft e devolve ja normalizados."""
    if not config.ms_enabled or not config.ms_refresh_token:
        return []
    try:
        token = await _get_ms_access_token(
            config.ms_client_id,
            config.ms_client_secret,
            config.ms_tenant_id,
            config.ms_refresh_token,
        )
        range_start, range_end = _calendar_window(start_time, end_time)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/calendarView",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$top": str(max(1, min(max_results, 100))),
                    "startDateTime": range_start.isoformat(),
                    "endDateTime": range_end.isoformat(),
                    "$select": "subject,start,end,onlineMeeting,bodyPreview,webLink",
                    "$orderby": "start/dateTime",
                },
            )
        data = resp.json()
        if "error" in data:
            raise Exception(data["error"]["message"])

        events = []
        for item in data.get("value", []):
            is_teams = item.get("onlineMeeting") is not None
            events.append(CalendarEvent(
                id=item["id"],
                title=item.get("subject", "Sem título"),
                start_time=_provider_datetime(item["start"]["dateTime"]),
                end_time=_provider_datetime(item["end"]["dateTime"]),
                source="teams" if is_teams else "outlook",
                meeting_url=item.get("onlineMeeting", {}).get("joinUrl") or item.get("webLink"),
                description=item.get("bodyPreview"),
            ))
        return events
    except Exception as e:
        logger.error(f"Microsoft Calendar error: {e}")
        if raise_on_error:
            raise RuntimeError(str(e)) from e
        return []


async def fetch_all_events(config: CalendarConfig) -> List[CalendarEvent]:
    """Le os eventos das duas fontes a partir da configuracao legada."""
    google_events, ms_events = await asyncio.gather(
        fetch_google_events(config),
        fetch_microsoft_events(config),
    )
    all_events = google_events + ms_events
    all_events.sort(key=lambda e: e.start_time)
    return all_events


async def create_google_account_event(
    account: dict,
    *,
    title: str,
    start_time: datetime,
    end_time: datetime,
    timezone_name: str,
    description: str | None = None,
    location: str | None = None,
    recurrence_until: date | None = None,
) -> CalendarEvent:
    """Creates an event in the connected account's primary Google calendar."""
    token = await _get_google_access_token(
        account.get("client_id", ""),
        account.get("client_secret", ""),
        account.get("refresh_token", ""),
    )
    payload = {
        "summary": title,
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": timezone_name,
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": timezone_name,
        },
    }
    if description:
        payload["description"] = description
    if location:
        payload["location"] = location
    if recurrence_until:
        until = datetime.combine(
            recurrence_until,
            datetime.max.time(),
            tzinfo=timezone.utc,
        ).strftime("%Y%m%dT%H%M%SZ")
        payload["recurrence"] = [f"RRULE:FREQ=WEEKLY;UNTIL={until}"]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    data = response.json()
    if response.is_error or "error" in data:
        detail = data.get("error", {})
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        raise RuntimeError(f"Google Calendar recusou o evento: {detail}")

    # O evento novo precisa aparecer na proxima leitura, nao so quando o resultado guardado vencer.
    await calendar_cache.invalidate(calendar_cache.account_key("google", account))
    account_id = account.get("id") or "google"
    return CalendarEvent(
        id=f"google:{account_id}:{data.get('id', '')}",
        title=data.get("summary") or title,
        start_time=start_time,
        end_time=end_time,
        source="google",
        meeting_url=data.get("hangoutLink") or data.get("htmlLink"),
        description=description,
    )


async def create_microsoft_account_event(
    account: dict,
    *,
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: str | None = None,
    location: str | None = None,
    recurrence_until: date | None = None,
    timezone_name: str = "UTC",
) -> CalendarEvent:
    """Creates an event in the connected account's default Outlook calendar."""
    token = await _get_ms_access_token(
        account.get("client_id", ""),
        account.get("client_secret", ""),
        account.get("tenant_id", "common"),
        account.get("refresh_token", ""),
    )
    start_utc = start_time.astimezone(timezone.utc)
    end_utc = end_time.astimezone(timezone.utc)
    microsoft_timezone = {
        "America/Sao_Paulo": "E. South America Standard Time",
        "UTC": "UTC",
    }.get(timezone_name, timezone_name)
    if recurrence_until:
        start_value = start_time.replace(tzinfo=None).isoformat(timespec="seconds")
        end_value = end_time.replace(tzinfo=None).isoformat(timespec="seconds")
        value_timezone = microsoft_timezone
    else:
        start_value = start_utc.replace(tzinfo=None).isoformat(timespec="seconds")
        end_value = end_utc.replace(tzinfo=None).isoformat(timespec="seconds")
        value_timezone = "UTC"
    payload = {
        "subject": title,
        "start": {
            "dateTime": start_value,
            "timeZone": value_timezone,
        },
        "end": {
            "dateTime": end_value,
            "timeZone": value_timezone,
        },
    }
    if description:
        payload["body"] = {"contentType": "text", "content": description}
    if location:
        payload["location"] = {"displayName": location}
    if recurrence_until:
        days = [
            "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        ]
        payload["recurrence"] = {
            "pattern": {
                "type": "weekly",
                "interval": 1,
                "daysOfWeek": [days[start_time.weekday()]],
            },
            "range": {
                "type": "endDate",
                "startDate": start_time.date().isoformat(),
                "endDate": recurrence_until.isoformat(),
                "recurrenceTimeZone": microsoft_timezone,
            },
        }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://graph.microsoft.com/v1.0/me/events",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    data = response.json()
    if response.is_error or "error" in data:
        detail = data.get("error", {})
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        raise RuntimeError(f"Microsoft Calendar recusou o evento: {detail}")

    await calendar_cache.invalidate(calendar_cache.account_key("microsoft", account))
    account_id = account.get("id") or "microsoft"
    online_meeting = data.get("onlineMeeting") or {}
    return CalendarEvent(
        id=f"microsoft:{account_id}:{data.get('id', '')}",
        title=data.get("subject") or title,
        start_time=start_time,
        end_time=end_time,
        source="teams" if online_meeting else "outlook",
        meeting_url=online_meeting.get("joinUrl") or data.get("webLink"),
        description=description,
    )


async def fetch_all_account_events(
    google_accounts: List[dict],
    microsoft_accounts: List[dict],
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_results: int = 25,
    max_age: float | None = None,
) -> List[CalendarEvent]:
    """Le, em paralelo, os eventos de todas as contas de calendario do usuario.

    `max_age` e a idade maxima, em segundos, de um resultado ja guardado que serve: `None` usa o
    padrao da instalacao e `0` obriga a ir ao provedor (e atualiza o que esta guardado).

    Returns:
        A lista unificada de eventos. Conta que falhou e simplesmente omitida - use
        `fetch_account_events_with_errors` quando o erro precisar chegar na tela.
    """
    events, errors = await fetch_account_events_with_errors(
        google_accounts,
        microsoft_accounts,
        start_time=start_time,
        end_time=end_time,
        max_results=max_results,
        max_age=max_age,
    )
    for error in errors:
        logger.error(f"Calendar account fetch failed: {error}")
    return events


async def fetch_account_events_with_errors(
    google_accounts: List[dict],
    microsoft_accounts: List[dict],
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_results: int = 25,
    max_age: float | None = None,
) -> tuple[List[CalendarEvent], List[str]]:
    """Igual a `fetch_all_account_events`, mas devolve tambem as falhas por conta.

    Returns:
        Uma tupla `(eventos, erros)`, para a interface poder dizer qual calendario
        nao respondeu em vez de mostrar uma agenda silenciosamente incompleta.
    """
    tasks: list[tuple[str, object]] = []

    for account in google_accounts:
        if account.get("refresh_token"):
            label = account.get("label") or "Google Calendar"
            tasks.append((label, _fetch_google_account_events(
                account,
                start_time=start_time,
                end_time=end_time,
                max_results=max_results,
                raise_on_error=True,
                max_age=max_age,
            )))

    for account in microsoft_accounts:
        if account.get("refresh_token"):
            label = account.get("label") or "Microsoft Calendar"
            tasks.append((label, _fetch_microsoft_account_events(
                account,
                start_time=start_time,
                end_time=end_time,
                max_results=max_results,
                raise_on_error=True,
                max_age=max_age,
            )))

    if not tasks:
        return [], []

    groups = await asyncio.gather(
        *(task for _, task in tasks),
        return_exceptions=True,
    )
    all_events: list[CalendarEvent] = []
    errors: list[str] = []
    for (label, _), group in zip(tasks, groups):
        if isinstance(group, BaseException):
            errors.append(f"{label}: {str(group)[:240]}")
        else:
            all_events.extend(group)
    all_events.sort(key=lambda e: e.start_time)
    return all_events, errors


async def _cached_account_events(
    provider: str,
    account: dict,
    fetch,
    *,
    max_age: float | None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_results: int = 25,
    **query,
) -> List[CalendarEvent]:
    """Eventos de uma conta, do armazenamento comum quando ha resultado recente que sirva.

    So grava depois de uma leitura bem-sucedida (`raise_on_error`): uma falha nao pode virar
    "agenda vazia" guardada para todo mundo.
    """
    key = calendar_cache.account_key(provider, account)
    start, end = _calendar_window(start_time, end_time)
    limit = max(1, min(max_results, 100))
    age = settings.calendar_cache_max_age_seconds if max_age is None else max_age
    if age > 0:
        hit = await calendar_cache.read(key, start, end, limit, age)
        if hit is not None:
            return hit
    events = await fetch(start_time=start, end_time=end, max_results=limit, **query)
    if query.get("raise_on_error"):
        await calendar_cache.write(key, start, end, limit, events)
    return events


async def _fetch_google_account_events(
    account: dict,
    *,
    max_age: float | None = None,
    **query,
) -> List[CalendarEvent]:
    config = CalendarConfig(
        google_client_id=account.get("client_id", ""),
        google_client_secret=account.get("client_secret", ""),
        google_refresh_token=account.get("refresh_token", ""),
        google_enabled=True,
    )

    async def fetch(**params) -> List[CalendarEvent]:
        return _tag_account_events(await fetch_google_events(config, **params), "google", account)

    return await _cached_account_events("google", account, fetch, max_age=max_age, **query)


async def _fetch_microsoft_account_events(
    account: dict,
    *,
    max_age: float | None = None,
    **query,
) -> List[CalendarEvent]:
    config = CalendarConfig(
        ms_client_id=account.get("client_id", ""),
        ms_client_secret=account.get("client_secret", ""),
        ms_tenant_id=account.get("tenant_id", "common"),
        ms_refresh_token=account.get("refresh_token", ""),
        ms_enabled=True,
    )

    async def fetch(**params) -> List[CalendarEvent]:
        return _tag_account_events(
            await fetch_microsoft_events(config, **params), "microsoft", account
        )

    return await _cached_account_events("microsoft", account, fetch, max_age=max_age, **query)


def _tag_account_events(
    events: List[CalendarEvent],
    provider: str,
    account: dict,
) -> List[CalendarEvent]:
    account_id = account.get("id") or account.get("account_id") or provider
    label = account.get("label") or provider
    for event in events:
        event.id = f"{provider}:{account_id}:{event.id}"
        if event.description:
            event.description = f"[{label}] {event.description}"
        else:
            event.description = f"[{label}]"
    return events
