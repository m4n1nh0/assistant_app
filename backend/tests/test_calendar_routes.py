import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytz
from fastapi import HTTPException

from app.models.schemas import (
    CalendarEvent,
    CalendarEventCreateRequest,
    ClassAgendaCreateRequest,
)
from app.routers import routes


def run(coro):
    return asyncio.run(coro)


def request(*, confirmed=True, account_id="google-1"):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    return CalendarEventCreateRequest(
        provider="google",
        account_id=account_id,
        title="Consulta",
        start_time=start,
        end_time=start + timedelta(hours=1),
        confirmed=confirmed,
    )


def test_create_event_requires_explicit_confirmation():
    with pytest.raises(HTTPException) as exc_info:
        run(routes.create_event(request(confirmed=False), user={"uid": "u1"}, db=object()))

    assert exc_info.value.status_code == 400


def test_create_event_uses_only_the_users_selected_account(monkeypatch):
    selected = {
        "id": "google-1",
        "refresh_token": "refresh",
        "client_id": "client",
        "client_secret": "secret",
    }

    async def accounts(db, user_id):
        assert user_id == "u1"
        return [selected]

    async def create(account, **kwargs):
        assert account is selected
        assert kwargs["title"] == "Consulta"
        return CalendarEvent(
            id="google:google-1:remote",
            title="Consulta",
            start_time=kwargs["start_time"],
            end_time=kwargs["end_time"],
            source="google",
        )

    monkeypatch.setattr(routes, "_load_google_accounts", accounts)
    monkeypatch.setattr(routes, "create_google_account_event", create)

    event = run(routes.create_event(request(), user={"uid": "u1"}, db=object()))

    assert event.id == "google:google-1:remote"


def test_create_event_rejects_account_not_owned_by_user(monkeypatch):
    async def accounts(db, user_id):
        return [{"id": "other", "refresh_token": "refresh"}]

    monkeypatch.setattr(routes, "_load_google_accounts", accounts)

    with pytest.raises(HTTPException) as exc_info:
        run(routes.create_event(request(), user={"uid": "u1"}, db=object()))

    assert exc_info.value.status_code == 404


def test_first_class_occurrence_skips_a_past_lesson_and_keeps_duration(monkeypatch):
    now = datetime(2026, 8, 17, 20, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(routes, "_datetime", FrozenDateTime)
    occurrence = routes._first_class_occurrence(
        date_from=date(2026, 8, 17),
        date_to=date(2026, 8, 31),
        weekday=0,
        start_value="10:00",
        end_value="12:00",
        event_timezone=pytz.timezone("America/Sao_Paulo"),
    )

    assert occurrence is not None
    start, end = occurrence
    assert start.date() == date(2026, 8, 24)
    assert start.strftime("%H:%M") == "10:00"
    assert end - start == timedelta(hours=2)


def test_first_class_occurrence_defaults_to_ninety_minutes(monkeypatch):
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(routes, "_datetime", FrozenDateTime)
    occurrence = routes._first_class_occurrence(
        date_from=date(2026, 8, 17),
        date_to=date(2026, 8, 31),
        weekday=0,
        start_value="19:00",
        end_value="",
        event_timezone=pytz.timezone("America/Sao_Paulo"),
    )

    assert occurrence is not None
    start, end = occurrence
    assert end - start == timedelta(minutes=90)


def test_class_agenda_creates_one_weekly_series_per_schedule(monkeypatch):
    first_day = date(2099, 8, 17)
    group = SimpleNamespace(
        id="class-1",
        tutor_id="tutor-1",
        code="3001",
        name="Presencial",
        discipline="Banco de Dados",
        semester="2099.2",
    )
    schedule = SimpleNamespace(
        id="schedule-1",
        class_group_id=group.id,
        weekday=first_day.weekday(),
        start_time="19:00",
        end_time="21:00",
    )

    class FakeScalars:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeResult:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return FakeScalars(self.values)

    class FakeDb:
        def __init__(self):
            self.responses = [[group], [schedule], []]
            self.added = []
            self.committed = False

        async def execute(self, statement):
            return FakeResult(self.responses.pop(0))

        def add(self, item):
            self.added.append(item)

        async def commit(self):
            self.committed = True

        async def rollback(self):
            pass

    async def accounts(db, user_id):
        return [{"id": "google-1", "refresh_token": "refresh"}]

    async def create(account, **kwargs):
        assert kwargs["recurrence_until"] == date(2099, 12, 31)
        return CalendarEvent(
            id="google:google-1:series-1",
            title=kwargs["title"],
            start_time=kwargs["start_time"],
            end_time=kwargs["end_time"],
            source="google",
        )

    monkeypatch.setattr(routes, "_load_google_accounts", accounts)
    monkeypatch.setattr(routes, "create_google_account_event", create)
    db = FakeDb()
    body = ClassAgendaCreateRequest(
        provider="google",
        account_id="google-1",
        class_ids=[group.id],
        date_from=first_day,
        date_to=date(2099, 12, 31),
        confirmed=True,
    )

    result = run(routes.create_class_agenda(
        body,
        user={"uid": "user-1", "tutor_id": "tutor-1"},
        db=db,
    ))

    assert result.created_series == 1
    assert result.failed_series == 0
    assert db.committed is True
    assert db.added[0].class_group_id == group.id
