import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from app.core import database
from app.models.schemas import AutomationUpdateRequest
from app.routers import automations, routes, tutor


def run(coro):
    return asyncio.run(coro)


class FakeDb:
    def __init__(self, row=None):
        self.row = row

    async def get(self, _model, _key):
        return self.row


def test_user_cannot_update_another_users_automation():
    foreign = SimpleNamespace(tutor_id="tutor-b")

    with pytest.raises(HTTPException) as exc_info:
        run(
            automations.update_automation(
                "automation-1",
                AutomationUpdateRequest(enabled=False),
                {"uid": "user-a", "tutor_id": "tutor-a"},
                FakeDb(foreign),
            )
        )

    assert exc_info.value.status_code == 404


def test_user_cannot_read_another_tutor_profile():
    with pytest.raises(HTTPException) as exc_info:
        run(
            tutor.get_tutor(
                "tutor-b",
                {"uid": "user-a", "tutor_id": "tutor-a"},
                FakeDb(),
            )
        )

    assert exc_info.value.status_code == 404


def test_calendar_oauth_state_binds_provider_user_and_account():
    state = routes._oauth_state("user-a", "google", "google-account")

    assert routes._read_oauth_state(state, "google") == (
        "user-a",
        "google-account",
    )
    with pytest.raises(HTTPException):
        routes._read_oauth_state(state, "microsoft")


def test_legacy_users_table_receives_multi_user_columns():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id VARCHAR(64) PRIMARY KEY, "
                "username VARCHAR(120) NOT NULL, "
                "password_hash VARCHAR(255) NOT NULL, "
                "created_at DATETIME)"
            )
        )
        database._add_compatibility_columns(connection)
        columns = {
            column["name"] for column in inspect(connection).get_columns("users")
        }
        indexes = inspect(connection).get_indexes("users")

    assert {"email", "role", "tutor_id", "is_active"} <= columns
    assert any(
        index.get("unique") and index.get("column_names") == ["email"]
        for index in indexes
    )
