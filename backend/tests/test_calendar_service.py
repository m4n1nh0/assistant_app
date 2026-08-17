import asyncio
from datetime import date, datetime, timezone
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

    async def get(self, url, **kwargs):
        self.__class__.calls.append((url, kwargs))
        return self.__class__.response


def test_oauth_urls_request_calendar_write_scopes_and_microsoft_pkce():
    google = parse_qs(urlparse(calendar_service.get_google_auth_url("g")).query)
    microsoft = parse_qs(
        urlparse(
            calendar_service.get_microsoft_auth_url(
                "m", state="signed-state", code_challenge="challenge"
            )
        ).query
    )

    assert google["scope"] == [
        "https://www.googleapis.com/auth/calendar.events"
    ]
    scopes = set(microsoft["scope"][0].split())
    assert {"Calendars.ReadWrite", "User.Read", "offline_access"} <= scopes
    assert microsoft["state"] == ["signed-state"]
    assert microsoft["code_challenge"] == ["challenge"]
    assert microsoft["code_challenge_method"] == ["S256"]


def test_microsoft_code_exchange_keeps_pkce_and_returns_session(monkeypatch):
    monkeypatch.setattr(calendar_service.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse({
        "access_token": "access-only-in-backend",
        "refresh_token": "persistent-session",
    })

    result = run(calendar_service.exchange_microsoft_code(
        "one-time-code",
        "application-id",
        "server-secret",
        redirect_uri="https://app.example/calendar/microsoft/oauth-callback",
        code_verifier="pkce-verifier",
    ))

    _, request = FakeAsyncClient.calls[0]
    assert request["data"]["code_verifier"] == "pkce-verifier"
    assert result["refresh_token"] == "persistent-session"


def test_microsoft_policy_errors_are_safe_and_actionable(monkeypatch):
    monkeypatch.setattr(calendar_service.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.response = FakeResponse({
        "error": "access_denied",
        "error_description": "AADSTS53003: Blocked by Conditional Access",
    }, is_error=True)

    try:
        run(calendar_service.exchange_microsoft_code(
            "code", "client", "secret", code_verifier="verifier"
        ))
        assert False, "the exchange should fail"
    except calendar_service.MicrosoftAuthenticationError as exc:
        assert "politica da organizacao" in str(exc)
        assert "AADSTS" not in str(exc)


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


def test_create_google_weekly_class_series_adds_recurrence(monkeypatch):
    async def token(*args):
        return "google-token"

    monkeypatch.setattr(calendar_service, "_get_google_access_token", token)
    monkeypatch.setattr(calendar_service.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse({"id": "series-1"})
    sao_paulo = pytz.timezone("America/Sao_Paulo")
    start = sao_paulo.localize(datetime(2026, 8, 17, 19, 0))

    run(calendar_service.create_google_account_event(
        {
            "id": "google-1",
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh",
        },
        title="Aula - Banco de Dados - 3001",
        start_time=start,
        end_time=start.replace(hour=21),
        timezone_name="America/Sao_Paulo",
        recurrence_until=date(2026, 12, 31),
    ))

    _, request = FakeAsyncClient.calls[0]
    assert request["json"]["recurrence"] == [
        "RRULE:FREQ=WEEKLY;UNTIL=20261231T235959Z"
    ]


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


def test_create_microsoft_weekly_class_series_keeps_local_time(monkeypatch):
    async def token(*args):
        return "microsoft-token"

    monkeypatch.setattr(calendar_service, "_get_ms_access_token", token)
    monkeypatch.setattr(calendar_service.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse({"id": "series-2"})
    sao_paulo = pytz.timezone("America/Sao_Paulo")
    start = sao_paulo.localize(datetime(2026, 8, 17, 19, 0))

    run(calendar_service.create_microsoft_account_event(
        {
            "id": "microsoft-1",
            "client_id": "client",
            "client_secret": "secret",
            "tenant_id": "common",
            "refresh_token": "refresh",
        },
        title="Aula - Banco de Dados - 3001",
        start_time=start,
        end_time=start.replace(hour=21),
        timezone_name="America/Sao_Paulo",
        recurrence_until=date(2026, 12, 31),
    ))

    _, request = FakeAsyncClient.calls[0]
    assert request["json"]["start"] == {
        "dateTime": "2026-08-17T19:00:00",
        "timeZone": "E. South America Standard Time",
    }
    assert request["json"]["recurrence"]["pattern"]["daysOfWeek"] == [
        "monday"
    ]
    assert request["json"]["recurrence"]["range"]["endDate"] == "2026-12-31"


def test_google_query_uses_requested_range_and_parses_all_day_events(monkeypatch):
    async def token(*args):
        return "google-token"

    monkeypatch.setattr(calendar_service, "_get_google_access_token", token)
    monkeypatch.setattr(calendar_service.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse({
        "items": [{
            "id": "all-day",
            "summary": "Feriado",
            "start": {"date": "2026-08-06"},
            "end": {"date": "2026-08-07"},
        }],
    })
    start = datetime(2026, 8, 6, tzinfo=timezone.utc)
    end = datetime(2026, 8, 7, tzinfo=timezone.utc)

    events = run(calendar_service.fetch_google_events(
        calendar_service.CalendarConfig(
            google_enabled=True,
            google_client_id="client",
            google_client_secret="secret",
            google_refresh_token="refresh",
        ),
        start_time=start,
        end_time=end,
        max_results=10,
    ))

    _, request = FakeAsyncClient.calls[0]
    assert request["params"]["timeMin"] == start.isoformat()
    assert request["params"]["timeMax"] == end.isoformat()
    assert request["params"]["maxResults"] == "10"
    assert events[0].start_time.tzinfo is not None


def test_account_query_keeps_partial_results_and_reports_failed_account(monkeypatch):
    async def google(account, **query):
        raise RuntimeError("token inválido")

    async def microsoft(account, **query):
        return [calendar_service.CalendarEvent(
            id="event-1",
            title="Planejamento",
            start_time=datetime(2026, 8, 6, 12, tzinfo=timezone.utc),
            source="outlook",
        )]

    monkeypatch.setattr(calendar_service, "_fetch_google_account_events", google)
    monkeypatch.setattr(
        calendar_service,
        "_fetch_microsoft_account_events",
        microsoft,
    )

    events, errors = run(calendar_service.fetch_account_events_with_errors(
        [{"id": "g1", "label": "Google", "refresh_token": "g"}],
        [{"id": "m1", "label": "Trabalho", "refresh_token": "m"}],
    ))

    assert [event.title for event in events] == ["Planejamento"]
    assert errors == ["Google: token inválido"]
