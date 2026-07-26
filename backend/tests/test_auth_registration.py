import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.schemas import RegisterRequest
from app.routers import routes


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def disable_notification_seed(monkeypatch):
    async def no_seed(_db, _user_id):
        return None

    monkeypatch.setattr(routes, "seed_admin_notification_config", no_seed)


class CountResult:
    def __init__(self, count):
        self.count = count

    def scalar_one(self):
        return self.count

    def scalar_one_or_none(self):
        return None


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

    async def flush(self):
        for row in self.added:
            if row.__class__.__name__ == "TutorModel" and row.id is None:
                row.id = "tutor-test"
            if row.__class__.__name__ == "UserModel" and row.id is None:
                row.id = "user-test"

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
    assert "Convite invalido" in str(exc_info.value.detail)


def test_register_consumes_invite_and_creates_admin_session(monkeypatch):
    invite = SimpleNamespace(
        used_at=None,
        role="admin",
        recipient_email="admin@example.com",
    )

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
    monkeypatch.setattr(
        routes,
        "account_token",
        lambda account: f"jwt:{account.role}",
    )
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
    assert len(db.added) == 3
    assert db.added[-1].username == "admin"
    assert db.added[-1].tutor_id == "tutor-test"


def test_register_keeps_legacy_first_account_flow_when_invite_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(registration_invite_required=False),
    )
    monkeypatch.setattr(routes, "hash_secret", lambda value: f"hash:{value}")
    monkeypatch.setattr(
        routes,
        "account_token",
        lambda account: f"jwt:{account.role}",
    )
    db = FakeDb()

    response = run(
        routes.register(
            RegisterRequest(username="admin", password="secret1"),
            db,
        )
    )

    assert response.success is True
    assert db.committed is True


def test_existing_install_accepts_only_admin_invited_user(monkeypatch):
    invite = SimpleNamespace(
        used_at=None,
        role="user",
        recipient_email="guest@example.com",
    )

    async def valid_invite(_db, _token):
        return invite

    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(registration_invite_required=False),
    )
    monkeypatch.setattr(routes, "lock_registration_invite", valid_invite)
    monkeypatch.setattr(routes, "hash_secret", lambda value: f"hash:{value}")
    monkeypatch.setattr(
        routes,
        "account_token",
        lambda account: f"jwt:{account.role}",
    )
    db = FakeDb(count=1)

    response = run(
        routes.register(
            RegisterRequest(
                username="guest",
                password="secret1",
                registration_token="invited",
            ),
            db,
        )
    )

    account = db.added[-1]
    assert response.token == "jwt:user"
    assert account.email == "guest@example.com"
    assert account.role == "user"
    assert invite.used_at is not None


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
