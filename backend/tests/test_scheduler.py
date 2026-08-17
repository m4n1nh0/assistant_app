import asyncio
from datetime import datetime, timedelta, timezone

from app.models.schemas import CalendarEvent, NotifConfig
from app.utils import scheduler


def run(coro):
    return asyncio.run(coro)


def test_scheduler_uses_configured_advance(monkeypatch):
    event = CalendarEvent(
        id="event-1",
        title="Aula",
        start_time=datetime.now(timezone.utc) + timedelta(minutes=20),
        source="google",
    )
    sent = []

    async def accounts(user_id):
        return [], []

    async def config(user_id=None):
        return NotifConfig(
            notify_15min=True,
            reminder_minutes=30,
            notify_on_time=False,
        )

    async def events(*args):
        return [event]

    async def send(message, cfg, event=None):
        sent.append(message)

    monkeypatch.setattr(scheduler, "_load_calendar_accounts", accounts)
    monkeypatch.setattr(scheduler, "load_notif_config", config)
    monkeypatch.setattr(scheduler, "fetch_all_account_events", events)
    monkeypatch.setattr(scheduler, "send_notification", send)
    scheduler._notified.clear()

    run(scheduler._sync_user("user-1"))

    assert len(sent) == 1
    assert "Em 30 minutos" in sent[0]


def test_scheduler_respects_disabled_advance(monkeypatch):
    event = CalendarEvent(
        id="event-2",
        title="Aula",
        start_time=datetime.now(timezone.utc) + timedelta(minutes=10),
        source="google",
    )
    sent = []

    async def accounts(user_id):
        return [], []

    async def config(user_id=None):
        return NotifConfig(
            notify_15min=False,
            reminder_minutes=30,
            notify_on_time=False,
        )

    async def events(*args):
        return [event]

    async def send(message, cfg, event=None):
        sent.append(message)

    monkeypatch.setattr(scheduler, "_load_calendar_accounts", accounts)
    monkeypatch.setattr(scheduler, "load_notif_config", config)
    monkeypatch.setattr(scheduler, "fetch_all_account_events", events)
    monkeypatch.setattr(scheduler, "send_notification", send)
    scheduler._notified.clear()

    run(scheduler._sync_user("user-1"))

    assert sent == []
