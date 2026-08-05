import asyncio
from urllib.parse import urlencode

import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from loguru import logger

from ..core.config import get_settings
from ..models.schemas import CalendarEvent, CalendarConfig

settings = get_settings()

GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
MICROSOFT_CALENDAR_SCOPE = "Calendars.ReadWrite offline_access"


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


async def fetch_google_events(config: CalendarConfig) -> List[CalendarEvent]:
    if not config.google_enabled or not config.google_refresh_token:
        return []
    try:
        token = await _get_google_access_token(
            config.google_client_id,
            config.google_client_secret,
            config.google_refresh_token,
        )
        now = datetime.now(timezone.utc)
        max_time = now + timedelta(days=7)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": now.isoformat(),
                    "timeMax": max_time.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "25",
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
                start_time=datetime.fromisoformat(start_raw),
                end_time=datetime.fromisoformat(end_raw) if end_raw else None,
                source="google",
                meeting_url=item.get("hangoutLink") or _extract_meet(item.get("description", "")),
                description=item.get("description"),
            ))
        return events
    except Exception as e:
        logger.error(f"Google Calendar error: {e}")
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
    qs = urlencode(params)
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{qs}"


async def exchange_microsoft_code(
    code: str,
    client_id: str,
    client_secret: str,
    tenant_id: str = "common",
    redirect_uri: str = "https://login.microsoftonline.com/common/oauth2/nativeclient",
) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": MICROSOFT_CALENDAR_SCOPE,
            },
        )
    data = resp.json()
    if "error" in data:
        raise Exception(data.get("error_description", data["error"]))
    return data["refresh_token"]


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
        raise Exception(data.get("error_description", data["error"]))
    return data["access_token"]


async def fetch_microsoft_events(config: CalendarConfig) -> List[CalendarEvent]:
    if not config.ms_enabled or not config.ms_refresh_token:
        return []
    try:
        token = await _get_ms_access_token(
            config.ms_client_id,
            config.ms_client_secret,
            config.ms_tenant_id,
            config.ms_refresh_token,
        )
        now = datetime.now(timezone.utc)
        max_time = now + timedelta(days=7)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/calendarView",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$top": "25",
                    "startDateTime": now.isoformat(),
                    "endDateTime": max_time.isoformat(),
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
                start_time=datetime.fromisoformat(item["start"]["dateTime"]).replace(tzinfo=timezone.utc),
                end_time=datetime.fromisoformat(item["end"]["dateTime"]).replace(tzinfo=timezone.utc),
                source="teams" if is_teams else "outlook",
                meeting_url=item.get("onlineMeeting", {}).get("joinUrl") or item.get("webLink"),
                description=item.get("bodyPreview"),
            ))
        return events
    except Exception as e:
        logger.error(f"Microsoft Calendar error: {e}")
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
    payload = {
        "subject": title,
        "start": {
            "dateTime": start_utc.replace(tzinfo=None).isoformat(timespec="seconds"),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end_utc.replace(tzinfo=None).isoformat(timespec="seconds"),
            "timeZone": "UTC",
        },
    }
    if description:
        payload["body"] = {"contentType": "text", "content": description}
    if location:
        payload["location"] = {"displayName": location}

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
) -> List[CalendarEvent]:
    tasks = []

    for account in google_accounts:
        if account.get("refresh_token"):
            tasks.append(_fetch_google_account_events(account))

    for account in microsoft_accounts:
        if account.get("refresh_token"):
            tasks.append(_fetch_microsoft_account_events(account))

    if not tasks:
        return []

    groups = await asyncio.gather(*tasks)
    all_events = [event for group in groups for event in group]
    all_events.sort(key=lambda e: e.start_time)
    return all_events


async def _fetch_google_account_events(account: dict) -> List[CalendarEvent]:
    config = CalendarConfig(
        google_client_id=account.get("client_id", ""),
        google_client_secret=account.get("client_secret", ""),
        google_refresh_token=account.get("refresh_token", ""),
        google_enabled=True,
    )
    events = await fetch_google_events(config)
    return _tag_account_events(events, "google", account)


async def _fetch_microsoft_account_events(account: dict) -> List[CalendarEvent]:
    config = CalendarConfig(
        ms_client_id=account.get("client_id", ""),
        ms_client_secret=account.get("client_secret", ""),
        ms_tenant_id=account.get("tenant_id", "common"),
        ms_refresh_token=account.get("refresh_token", ""),
        ms_enabled=True,
    )
    events = await fetch_microsoft_events(config)
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
