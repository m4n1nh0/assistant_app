import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.schemas import CalendarEvent, CalendarEventCreateRequest
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

