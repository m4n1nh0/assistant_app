import asyncio
from urllib.parse import urlencode

import httpx
from datetime import date, datetime, timezone, timedelta
from typing import List, Optional
from loguru import logger

from ..core.config import get_settings
from ..models.schemas import CalendarEvent, CalendarConfig

settings = get_settings()

GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
MICROSOFT_CALENDAR_SCOPE = (
    "openid profile email offline_access User.Read Calendars.ReadWrite"
)


class MicrosoftAuthenticationError(RuntimeError):
    """Safe, user-facing Microsoft authentication failure."""


def microsoft_auth_error_message(error: str, description: str = "") -> str:
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


async def exchange_google_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob",
) -> str:
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
    return data["refresh_token"]


async def _get_google_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> str:
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
        raise Exception(data.get("error_description", data["error"]))
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
) -> List[CalendarEvent]:
    events, errors = await fetch_account_events_with_errors(
        google_accounts,
        microsoft_accounts,
        start_time=start_time,
        end_time=end_time,
        max_results=max_results,
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
) -> tuple[List[CalendarEvent], List[str]]:
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


async def _fetch_google_account_events(
    account: dict,
    **query,
) -> List[CalendarEvent]:
    config = CalendarConfig(
        google_client_id=account.get("client_id", ""),
        google_client_secret=account.get("client_secret", ""),
        google_refresh_token=account.get("refresh_token", ""),
        google_enabled=True,
    )
    events = await fetch_google_events(config, **query)
    return _tag_account_events(events, "google", account)


async def _fetch_microsoft_account_events(
    account: dict,
    **query,
) -> List[CalendarEvent]:
    config = CalendarConfig(
        ms_client_id=account.get("client_id", ""),
        ms_client_secret=account.get("client_secret", ""),
        ms_tenant_id=account.get("tenant_id", "common"),
        ms_refresh_token=account.get("refresh_token", ""),
        ms_enabled=True,
    )
    events = await fetch_microsoft_events(config, **query)
    return _tag_account_events(events, "microsoft", account)


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
