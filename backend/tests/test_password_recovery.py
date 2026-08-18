import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import security
from app.models.schemas import (
    LoginRequest,
    PasswordRecoveryConfirmRequest,
    PasswordRecoveryRequest,
)
from app.routers import routes
from app.services import password_recovery_service as service


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
    def __init__(self, results, accounts=None):
        self.results = list(results)
        self.accounts = accounts or {}
        self.added = []
        self.flushed = False
        self.committed = False
        self.rolled_back = False

    async def execute(self, _query):
        return self.results.pop(0)

    async def get(self, _model, item_id):
        return self.accounts.get(item_id)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def recovery_settings(**overrides):
    values = {
        "jwt_secret": "test-secret",
        "password_reset_token_expire_minutes": 30,
        "password_reset_request_cooldown_seconds": 60,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_request_stores_only_digest_and_sends_token(monkeypatch):
    account = SimpleNamespace(
        id="user-1",
        username="mariano",
        email="mariano@example.com",
        is_active=True,
    )
    db = FakeDb(
        [
            FakeResult(scalar=account),
            FakeResult(scalar=None),
            FakeResult(rows=[]),
        ]
    )
    delivered = {}

    async def fake_send(recipient, username, token, expires_at):
        delivered.update(
            recipient=recipient,
            username=username,
            token=token,
            expires_at=expires_at,
        )

    monkeypatch.setattr(service, "settings", recovery_settings())
    monkeypatch.setattr(service, "registration_delivery_configured", lambda _: True)
    monkeypatch.setattr(service, "_send_password_reset_email", fake_send)

    assert run(service.issue_password_reset_token(db, "mariano")) is True
    assert db.flushed is True
    assert db.committed is True
    assert len(db.added) == 1
    assert db.added[0].token_hash != delivered["token"]
    assert db.added[0].token_hash == service.password_reset_token_digest(
        delivered["token"]
    )
    assert delivered["recipient"] == "mariano@example.com"
    assert delivered["username"] == "mariano"


def test_unknown_account_keeps_request_generic_and_creates_nothing(monkeypatch):
    db = FakeDb([FakeResult(scalar=None)])
    monkeypatch.setattr(service, "settings", recovery_settings())

    issued = run(service.issue_password_reset_token(db, "missing@example.com"))

    assert issued is False
    assert db.added == []
    assert db.committed is False


def test_valid_token_changes_password_once_and_revokes_sessions(monkeypatch):
    reset = SimpleNamespace(
        user_id="user-1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        used_at=None,
        revoked_at=None,
    )
    account = SimpleNamespace(
        is_active=True,
        password_hash="old-hash",
        auth_version=2,
    )
    db = FakeDb(
        [FakeResult(scalar=reset)],
        accounts={"user-1": account},
    )
    monkeypatch.setattr(service, "settings", recovery_settings())

    consumed = run(
        service.consume_password_reset_token(db, "one-time-token", "new-hash")
    )

    assert consumed is True
    assert account.password_hash == "new-hash"
    assert account.auth_version == 3
    assert reset.used_at is not None
    assert db.committed is True


def test_expired_token_is_rejected(monkeypatch):
    reset = SimpleNamespace(
        user_id="user-1",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        used_at=None,
        revoked_at=None,
    )
    db = FakeDb([FakeResult(scalar=reset)])
    monkeypatch.setattr(service, "settings", recovery_settings())

    assert (
        run(service.consume_password_reset_token(db, "expired", "new-hash"))
        is False
    )
    assert db.committed is False


def test_public_request_does_not_reveal_if_account_exists(monkeypatch):
    async def not_issued(_db, identifier):
        assert identifier == "unknown"
        return False

    monkeypatch.setattr(routes, "issue_password_reset_token", not_issued)
    response = run(
        routes.request_password_recovery(
            PasswordRecoveryRequest(identifier="unknown"),
            FakeDb([]),
        )
    )

    assert response.success is True
    assert "Se houver uma conta ativa" in response.message


def test_login_accepts_the_email_used_for_recovery(monkeypatch):
    account = SimpleNamespace(
        id="user-1",
        username="mariano",
        email="mariano@example.com",
        role="admin",
        tutor_id="tutor-1",
        is_active=True,
        auth_version=0,
        password_hash="saved-hash",
    )
    db = FakeDb([FakeResult(scalar=account)])
    monkeypatch.setattr(routes, "verify_secret", lambda plain, hashed: True)
    monkeypatch.setattr(routes, "account_token", lambda _account: "new-jwt")

    response = run(
        routes.login(
            LoginRequest(username="mariano@example.com", password="secret1"),
            db,
        )
    )

    assert response.success is True
    assert response.token == "new-jwt"


def test_confirm_rejects_invalid_or_used_token(monkeypatch):
    async def invalid(_db, _token, _password_hash):
        return False

    monkeypatch.setattr(routes, "consume_password_reset_token", invalid)
    monkeypatch.setattr(routes, "hash_secret", lambda value: f"hash:{value}")

    with pytest.raises(HTTPException) as exc_info:
        run(
            routes.confirm_password_recovery(
                PasswordRecoveryConfirmRequest(
                    token="invalid",
                    new_password="secret1",
                ),
                FakeDb([]),
            )
        )

    assert exc_info.value.status_code == 400
    assert "expirado" in str(exc_info.value.detail)


def test_password_reset_version_invalidates_previous_session(monkeypatch):
    account = SimpleNamespace(
        id="user-1",
        username="mariano",
        email="mariano@example.com",
        role="admin",
        tutor_id="tutor-1",
        is_active=True,
        auth_version=3,
    )
    db = FakeDb([], accounts={"user-1": account})
    monkeypatch.setattr(
        security,
        "decode_token",
        lambda _token: {"uid": "user-1", "sub": "mariano", "ver": 2},
    )

    with pytest.raises(HTTPException) as exc_info:
        run(security.resolve_token_user("old-jwt", db))

    assert exc_info.value.status_code == 401
    assert "Sessao invalidada" in str(exc_info.value.detail)
