import asyncio
import json
from types import SimpleNamespace

from app.models.schemas import NotifConfig
from app.services import runtime_config_service as service


def run(coro):
    return asyncio.run(coro)


class FakeDb:
    def __init__(self, value=None):
        self.row = SimpleNamespace(value=value) if value is not None else None
        self.added = None
        self.committed = False
        self.last_key = None

    async def get(self, _model, _key):
        self.last_key = _key
        return self.row

    def add(self, row):
        self.added = row
        self.row = row

    async def commit(self):
        self.committed = True


def _settings(**overrides):
    defaults = {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "wa_provider": "callmebot",
        "wa_number": "",
        "wa_token": "",
        "wa_sid": "",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_load_notif_config_prefers_database_values(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: _settings(
        telegram_bot_token="env-token",
        wa_number="env-number",
    ))
    db = FakeDb(json.dumps({
        "telegram_token": "db-token",
        "telegram_chat_id": "db-chat",
        "telegram_enabled": True,
        "wa_provider": "zapi",
        "wa_number": "db-number",
        "wa_token": "db-wa-token",
        "wa_enabled": True,
    }))

    cfg = run(service.load_notif_config(db))

    assert cfg.telegram_token == "db-token"
    assert cfg.telegram_chat_id == "db-chat"
    assert cfg.wa_provider == "zapi"
    assert cfg.wa_number == "db-number"
    assert cfg.telegram_enabled is True
    assert cfg.wa_enabled is True


def test_load_notif_config_accepts_camel_case_legacy_payload(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: _settings())
    db = FakeDb(json.dumps({
        "tgToken": "camel-token",
        "tgChatId": "camel-chat",
        "tgEnabled": True,
        "waProvider": "twilio",
        "waNumber": "camel-number",
        "waToken": "camel-wa-token",
        "waEnabled": True,
        "notify15min": False,
        "reminderMinutes": "30",
    }))

    cfg = run(service.load_notif_config(db))

    assert cfg.telegram_token == "camel-token"
    assert cfg.telegram_chat_id == "camel-chat"
    assert cfg.wa_provider == "twilio"
    assert cfg.notify_15min is False
    assert cfg.reminder_minutes == 30


def test_save_notif_config_stores_snake_case_payload(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: _settings())
    db = FakeDb()
    cfg = NotifConfig(
        telegram_token="saved-token",
        telegram_chat_id="saved-chat",
        telegram_enabled=True,
        wa_provider="callmebot",
        wa_number="5511999999999",
        wa_token="saved-wa-token",
        wa_enabled=True,
        reminder_minutes=45,
    )

    saved = run(service.save_notif_config(db, cfg))
    payload = json.loads(db.row.value)

    assert db.committed is True
    assert payload["telegram_token"] == "saved-token"
    assert payload["telegram_enabled"] is True
    assert payload["wa_number"] == "5511999999999"
    assert payload["reminder_minutes"] == 45
    assert saved.telegram_token == "saved-token"


def test_load_notif_config_clamps_invalid_reminder_minutes(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: _settings())
    db = FakeDb(json.dumps({"reminder_minutes": 9999}))

    cfg = run(service.load_notif_config(db))

    assert cfg.reminder_minutes == 1440


def test_notification_config_is_scoped_by_authenticated_user(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: _settings())
    db = FakeDb()

    run(
        service.save_notif_config(
            db,
            NotifConfig(telegram_token="private-token"),
            user_id="user-123",
        )
    )

    assert db.added.key == "user:user-123:notif"
