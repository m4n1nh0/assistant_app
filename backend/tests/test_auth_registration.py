import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.schemas import RegisterRequest
from app.routers import routes


def run(coro):
    return asyncio.run(coro)


class CountResult:
    def __init__(self, count):
        self.count = count

    def scalar_one(self):
        return self.count


class FakeDb:
    def __init__(self, count=0):
        self.count = count
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, _query):
        return CountResult(self.count)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def test_register_requires_valid_admin_token_when_enabled(monkeypatch):
    async def missing_invite(_db, _token):
        return None

    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(registration_invite_required=True),
    )
    monkeypatch.setattr(routes, "lock_registration_invite", missing_invite)

    with pytest.raises(HTTPException) as exc_info:
        run(
            routes.register(
                RegisterRequest(
                    username="admin",
                    password="secret1",
                    registration_token="invalid",
                ),
                FakeDb(),
            )
        )

    assert exc_info.value.status_code == 403
    assert "Token administrativo" in str(exc_info.value.detail)


def test_register_consumes_invite_and_creates_admin_session(monkeypatch):
    invite = SimpleNamespace(used_at=None)

    async def valid_invite(_db, token):
        assert token == "valid-token"
        return invite

    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(registration_invite_required=True),
    )
    monkeypatch.setattr(routes, "lock_registration_invite", valid_invite)
    monkeypatch.setattr(routes, "hash_secret", lambda value: f"hash:{value}")
    monkeypatch.setattr(routes, "create_token", lambda data: f"jwt:{data['role']}")
    db = FakeDb()

    response = run(
        routes.register(
            RegisterRequest(
                username="admin",
                password="secret1",
                registration_token="valid-token",
            ),
            db,
        )
    )

    assert response.success is True
    assert response.token == "jwt:admin"
    assert invite.used_at is not None
    assert db.committed is True
    assert len(db.added) == 1
    assert db.added[0].username == "admin"


def test_register_keeps_legacy_first_account_flow_when_invite_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(registration_invite_required=False),
    )
    monkeypatch.setattr(routes, "hash_secret", lambda value: f"hash:{value}")
    monkeypatch.setattr(routes, "create_token", lambda data: f"jwt:{data['role']}")
    db = FakeDb()

    response = run(
        routes.register(
            RegisterRequest(username="admin", password="secret1"),
            db,
        )
    )

    assert response.success is True
    assert db.committed is True


def test_auth_status_exposes_masked_invite_delivery_state(monkeypatch):
    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(
            registration_invite_required=True,
            registration_admin_email="admin@example.com",
        ),
    )
    monkeypatch.setattr(
        routes,
        "registration_delivery_configured",
        lambda: True,
    )

    response = run(routes.auth_status(FakeDb()))

    assert response.needs_setup is True
    assert response.registration_requires_token is True
    assert response.registration_delivery_configured is True
    assert response.admin_email_hint == "ad***@example.com"
