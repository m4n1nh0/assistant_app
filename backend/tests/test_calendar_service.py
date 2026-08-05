import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytz

from app.services import calendar_service


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, data, *, is_error=False):
        self._data = data
        self.is_error = is_error

    def json(self):
        return self._data


class FakeAsyncClient:
    calls = []
    response = FakeResponse({})

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.__class__.calls.append((url, kwargs))
        return self.__class__.response


def test_oauth_urls_request_calendar_write_scopes():
    google = parse_qs(urlparse(calendar_service.get_google_auth_url("g")).query)
    microsoft = parse_qs(
        urlparse(calendar_service.get_microsoft_auth_url("m")).query
    )

    assert google["scope"] == [
        "https://www.googleapis.com/auth/calendar.events"
    ]
    assert microsoft["scope"] == ["Calendars.ReadWrite offline_access"]


def test_create_google_event_posts_to_primary_calendar(monkeypatch):
    async def token(*args):
        return "google-token"

    monkeypatch.setattr(calendar_service, "_get_google_access_token", token)
    monkeypatch.setattr(calendar_service.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse(
        {"id": "remote-1", "summary": "Consulta", "htmlLink": "https://event"}
    )
    start = datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc)
    end = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)

    event = run(
        calendar_service.create_google_account_event(
            {
                "id": "google-1",
                "client_id": "client",
                "client_secret": "secret",
                "refresh_token": "refresh",
            },
            title="Consulta",
            start_time=start,
            end_time=end,
            timezone_name="America/Sao_Paulo",
        )
    )

    url, request = FakeAsyncClient.calls[0]
    assert url.endswith("/calendars/primary/events")
    assert request["headers"]["Authorization"] == "Bearer google-token"
    assert request["json"]["summary"] == "Consulta"
    assert request["json"]["start"]["dateTime"] == start.isoformat()
    assert event.id == "google:google-1:remote-1"
    assert event.source == "google"


def test_create_microsoft_event_posts_utc_times(monkeypatch):
    async def token(*args):
        return "microsoft-token"

    monkeypatch.setattr(calendar_service, "_get_ms_access_token", token)
    monkeypatch.setattr(calendar_service.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse(
        {"id": "remote-2", "subject": "Planejamento", "webLink": "https://event"}
    )
    sao_paulo = pytz.timezone("America/Sao_Paulo")
    start = sao_paulo.localize(datetime(2026, 8, 10, 9, 0))
    end = sao_paulo.localize(datetime(2026, 8, 10, 10, 0))

    event = run(
        calendar_service.create_microsoft_account_event(
            {
                "id": "microsoft-1",
                "client_id": "client",
                "client_secret": "secret",
                "tenant_id": "common",
                "refresh_token": "refresh",
            },
            title="Planejamento",
            start_time=start,
            end_time=end,
        )
    )

    url, request = FakeAsyncClient.calls[0]
    assert url == "https://graph.microsoft.com/v1.0/me/events"
    assert request["json"]["start"] == {
        "dateTime": "2026-08-10T12:00:00",
        "timeZone": "UTC",
    }
    assert event.id == "microsoft:microsoft-1:remote-2"
    assert event.source == "outlook"
