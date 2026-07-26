import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import registration_invite_service as service


def run(coro):
    return asyncio.run(coro)


class FakeResult:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.flushed = False
        self.committed = False
        self.rolled_back = False

    async def execute(self, _query):
        return self.results.pop(0)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def invite_settings(**overrides):
    values = {
        "jwt_secret": "test-secret",
        "registration_admin_email": "admin@example.com",
        "registration_token_expire_minutes": 30,
        "registration_token_request_cooldown_seconds": 60,
        "smtp_username": "mailer",
        "smtp_from": "assistant@example.com",
        "brevo_api_key": "brevo-key",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_masks_admin_email_without_exposing_full_address():
    assert service.mask_email("administrator@example.com") == "ad***********@example.com"
    assert service.mask_email("x@example.com") == "x***@example.com"
    assert service.mask_email("invalid") == ""


def test_delivery_requires_recipient_sender_and_api_key(monkeypatch):
    monkeypatch.setattr(service, "settings", invite_settings())
    assert service.registration_delivery_configured() is True

    monkeypatch.setattr(
        service,
        "settings",
        invite_settings(brevo_api_key=""),
    )
    assert service.registration_delivery_configured() is False


def test_issue_token_stores_only_digest_and_revokes_previous(monkeypatch):
    previous = SimpleNamespace(revoked_at=None)
    db = FakeDb(
        [
            FakeResult(scalar=None),
            FakeResult(rows=[previous]),
        ]
    )
    delivered = {}

    async def fake_send(token, expires_at, recipient_email=None):
        delivered["token"] = token
        delivered["expires_at"] = expires_at

    monkeypatch.setattr(service, "settings", invite_settings())
    monkeypatch.setattr(service, "_send_registration_email", fake_send)

    email_hint, expires_at = run(service.issue_registration_token(db))

    assert email_hint == "ad***@example.com"
    assert db.flushed is True
    assert db.committed is True
    assert db.rolled_back is False
    assert previous.revoked_at is not None
    assert len(db.added) == 1
    assert db.added[0].token_hash != delivered["token"]
    assert db.added[0].token_hash == service.registration_token_digest(
        delivered["token"]
    )
    assert expires_at == delivered["expires_at"]


def test_lock_registration_invite_rejects_expired_token(monkeypatch):
    expired = SimpleNamespace(
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    db = FakeDb([FakeResult(scalar=expired)])
    monkeypatch.setattr(service, "settings", invite_settings())

    invite = run(service.lock_registration_invite(db, "expired-token"))

    assert invite is None


def test_active_token_prevents_email_spam_and_token_replacement(monkeypatch):
    active = SimpleNamespace(
        used_at=None,
        revoked_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db = FakeDb([FakeResult(scalar=active)])
    monkeypatch.setattr(service, "settings", invite_settings())

    with pytest.raises(service.RegistrationTokenCooldownError) as exc_info:
        run(service.issue_registration_token(db))

    assert exc_info.value.retry_after_seconds > 60
    assert db.added == []


def test_api_delivery_posts_to_brevo_with_admin_recipient(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 201

        def raise_for_status(self):
            pass

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

        async def post(self, url, headers, json):
            captured.update(url=url, headers=headers, json=json)
            return FakeResponse()

    monkeypatch.setattr(service, "settings", invite_settings())
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    run(service._send_registration_email("one-time-token", expires_at))

    assert captured["url"] == service.BREVO_SEND_URL
    assert captured["headers"]["api-key"] == "brevo-key"
    assert captured["json"]["sender"]["email"] == "assistant@example.com"
    assert captured["json"]["to"] == [{"email": "admin@example.com"}]
    assert "one-time-token" in captured["json"]["textContent"]
