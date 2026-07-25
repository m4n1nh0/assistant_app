import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import database_seed


def run(coro):
    return asyncio.run(coro)


class FakeDb:
    def __init__(self, marker=None):
        self.marker = marker
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False

    async def get(self, _model, key):
        if key == database_seed.SEED_MARKER_KEY:
            return self.marker
        return None

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def test_seed_is_disabled_by_default():
    for value in (None, "", "false", "off", "0"):
        assert database_seed.database_seed_requested(value) is False
        assert run(database_seed.apply_database_seed(value)) is False


def test_unknown_seed_name_is_rejected():
    with pytest.raises(ValueError, match="Valor suportado"):
        run(database_seed.apply_database_seed("demo-v2"))


def test_applied_seed_marker_skips_reexecution(monkeypatch):
    db = FakeDb(marker=SimpleNamespace(value="{}"))
    called = False

    async def fake_seed(_db):
        nonlocal called
        called = True

    monkeypatch.setattr(database_seed, "seed_demo_data", fake_seed)

    applied = run(database_seed.apply_database_seed("demo-v1", lambda: db))

    assert applied is False
    assert called is False
    assert db.committed is False


def test_seed_and_marker_are_committed_together(monkeypatch):
    db = FakeDb()

    async def fake_seed(received_db):
        received_db.add(SimpleNamespace(kind="demo-row"))

    monkeypatch.setattr(database_seed, "seed_demo_data", fake_seed)

    applied = run(database_seed.apply_database_seed(" DEMO-V1 ", lambda: db))

    assert applied is True
    assert db.committed is True
    assert db.rolled_back is False
    assert len(db.added) == 2
    marker = db.added[-1]
    assert marker.key == database_seed.SEED_MARKER_KEY
    assert json.loads(marker.value)["seed"] == "demo-v1"


def test_seed_failure_rolls_back_transaction(monkeypatch):
    db = FakeDb()

    async def failing_seed(_db):
        raise RuntimeError("seed failed")

    monkeypatch.setattr(database_seed, "seed_demo_data", failing_seed)

    with pytest.raises(RuntimeError, match="seed failed"):
        run(database_seed.apply_database_seed("demo-v1", lambda: db))

    assert db.committed is False
    assert db.rolled_back is True


def test_concurrent_seed_uses_marker_from_other_replica(monkeypatch):
    db = FakeDb()

    async def fake_seed(_db):
        return None

    async def failing_commit():
        raise IntegrityError("INSERT", {}, RuntimeError("duplicate"))

    original_get = db.get

    async def get_after_rollback(model, key):
        if db.rolled_back and key == database_seed.SEED_MARKER_KEY:
            return SimpleNamespace(value="{}")
        return await original_get(model, key)

    db.commit = failing_commit
    db.get = get_after_rollback
    monkeypatch.setattr(database_seed, "seed_demo_data", fake_seed)

    applied = run(database_seed.apply_database_seed("demo-v1", lambda: db))

    assert applied is False
    assert db.rolled_back is True
