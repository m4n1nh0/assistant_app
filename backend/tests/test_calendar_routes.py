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


# --- reconectar Google nao pode duplicar a conta ---------------------------------------------


def _store(monkeypatch, accounts):
    saved = {}

    async def load(db, key, user_id):
        return [dict(item) for item in accounts]

    async def save(db, key, items, user_id):
        saved["items"] = items

    monkeypatch.setattr(routes, "_load_account_store", load)
    monkeypatch.setattr(routes, "_save_account_store", save)
    return saved


def test_reconectar_usa_a_conta_pedida(monkeypatch):
    _store(monkeypatch, [{"id": "g1", "refresh_token": "r"}, {"id": "g2", "refresh_token": "r"}])

    assert run(routes._google_attempt_id(None, "u1", "g1")) == "g1"


def test_tentativa_abandonada_e_reaproveitada_em_vez_de_abrir_outra(monkeypatch):
    _store(monkeypatch, [{"id": "g1", "refresh_token": "r"}, {"id": "pendente"}])

    assert run(routes._google_attempt_id(None, "u1", None)) == "pendente"


def test_sem_nada_pendente_nasce_conta_nova(monkeypatch):
    _store(monkeypatch, [{"id": "g1", "refresh_token": "r"}])

    novo = run(routes._google_attempt_id(None, "u1", None))

    assert novo.startswith("google_") and novo != "g1"


def test_conta_renovada_substitui_a_do_mesmo_email_e_limpa_pendentes(monkeypatch):
    saved = _store(monkeypatch, [
        {"id": "velha", "refresh_token": "r", "email": "Ana@x.com"},
        {"id": "outra-pessoa", "refresh_token": "r", "email": "bia@x.com"},
        {"id": "pendente"},
        {"id": "nova", "refresh_token": "r2", "email": "ana@x.com"},
    ])

    run(routes._drop_superseded_google_accounts(None, "u1", "nova", "ana@x.com"))

    assert [item["id"] for item in saved["items"]] == ["outra-pessoa", "nova"]


def test_sem_email_so_as_pendentes_saem(monkeypatch):
    saved = _store(monkeypatch, [
        {"id": "a", "refresh_token": "r"}, {"id": "pendente"}, {"id": "nova", "refresh_token": "r2"},
    ])

    run(routes._drop_superseded_google_accounts(None, "u1", "nova", ""))

    assert [item["id"] for item in saved["items"]] == ["a", "nova"]


def test_conta_google_recusada_aparece_para_reconectar_com_o_motivo(monkeypatch):
    conta = {"id": "g1", "refresh_token": "r", "client_id": "c", "label": "Google Calendar"}

    async def google(db, user_id, include_pending=False):
        return [dict(conta)]

    async def vazio(db, user_id, include_pending=False):
        return []

    monkeypatch.setattr(routes, "_load_google_accounts", google)
    monkeypatch.setattr(routes, "_load_microsoft_accounts", vazio)
    monkeypatch.setattr(routes, "google_auth_failure", lambda account: "Google recusou renovar.")

    google_conta = run(routes.calendar_accounts(user={"uid": "u1"}, db=object()))["google"][0]

    assert google_conta["connected"] is False
    assert google_conta["status"] == "reconnect_required"
    assert google_conta["error"] == "Google recusou renovar."
