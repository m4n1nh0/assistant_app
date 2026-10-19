"""Agenda: o provedor e lido uma vez e o resultado serve a todos.

Agendador, interface e chat liam o Google cada um por conta propria, e cada leitura era um pedido
de token mais um pedido de eventos. Aqui o armazenamento comum e o cache de token sao exercitados
contra um provedor falso que conta as idas.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models.schemas import CalendarEvent
from app.services import calendar_cache, calendar_service as cs


def run(coro):
    return asyncio.run(coro)


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
ACCOUNT = {"id": "a1", "label": "Google", "client_id": "cid", "client_secret": "sec", "refresh_token": "rt-1"}


def ev(eid, start, *, minutes=60):
    return CalendarEvent(id=eid, title=eid, start_time=start, end_time=start + timedelta(minutes=minutes), source="google")


class Provider:
    """Provedor falso: conta as leituras e devolve os eventos que tiver dentro do periodo."""

    def __init__(self, events):
        self.events = events
        self.calls = []
        self.fail = False

    async def fetch(self, config, *, start_time=None, end_time=None, max_results=25, raise_on_error=False):
        self.calls.append((start_time, end_time, max_results))
        if self.fail:
            raise RuntimeError("Google fora do ar")
        inside = [e for e in self.events if e.start_time < end_time and (e.end_time or e.start_time) > start_time]
        return [e.model_copy(deep=True) for e in sorted(inside, key=lambda e: e.start_time)[:max_results]]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    calendar_cache.clear_memory()
    cs.clear_token_cache()
    monkeypatch.setattr(calendar_cache, "get_redis_client", lambda: None)
    yield
    calendar_cache.clear_memory()
    cs.clear_token_cache()


@pytest.fixture
def provider(monkeypatch):
    p = Provider([ev("e1", NOW + timedelta(hours=1)), ev("e2", NOW + timedelta(days=2)), ev("e3", NOW + timedelta(days=10))])
    monkeypatch.setattr(cs, "fetch_google_events", p.fetch)
    return p


def read(**kwargs):
    return run(cs.fetch_account_events_with_errors([ACCOUNT], [], **kwargs))


def titles(result):
    return [e.title for e in result[0]]


# --- armazenamento comum -----------------------------------------------------------


def test_second_read_is_served_from_the_store_without_calling_the_provider(provider):
    first = read(start_time=NOW, end_time=NOW + timedelta(days=7))
    second = read(start_time=NOW, end_time=NOW + timedelta(days=7))

    assert len(provider.calls) == 1
    assert titles(first) == titles(second) == ["e1", "e2"]


def test_a_read_that_starts_a_little_later_is_covered_by_what_is_stored(provider):
    read(start_time=NOW, end_time=NOW + timedelta(days=7))

    later = read(start_time=NOW + timedelta(minutes=3), end_time=NOW + timedelta(days=5))

    assert len(provider.calls) == 1
    assert titles(later) == ["e1", "e2"]


def test_a_narrower_period_gets_only_its_events_from_the_store(provider):
    read(start_time=NOW, end_time=NOW + timedelta(days=7))

    tomorrow = read(start_time=NOW, end_time=NOW + timedelta(hours=6))

    assert len(provider.calls) == 1
    assert titles(tomorrow) == ["e1"]


def test_a_period_the_store_does_not_cover_goes_to_the_provider(provider):
    read(start_time=NOW, end_time=NOW + timedelta(days=3))

    wider = read(start_time=NOW, end_time=NOW + timedelta(days=30))
    earlier = read(start_time=NOW - timedelta(days=5), end_time=NOW + timedelta(days=1))

    assert len(provider.calls) == 3
    assert titles(wider) == ["e1", "e2", "e3"]
    assert titles(earlier) == ["e1"]


def test_max_age_zero_forces_a_provider_read_and_refreshes_the_store(provider):
    read(start_time=NOW, end_time=NOW + timedelta(days=7))
    provider.events.append(ev("novo", NOW + timedelta(hours=2)))

    forced = read(start_time=NOW, end_time=NOW + timedelta(days=7), max_age=0)
    after = read(start_time=NOW, end_time=NOW + timedelta(days=7))

    assert len(provider.calls) == 2
    assert titles(forced) == titles(after) == ["e1", "novo", "e2"]


def test_a_stored_result_older_than_max_age_is_not_used(provider, monkeypatch):
    read(start_time=NOW, end_time=NOW + timedelta(days=7))
    for snapshot in calendar_cache._memory.values():
        snapshot.fetched_at -= 600

    read(start_time=NOW, end_time=NOW + timedelta(days=7), max_age=300)

    assert len(provider.calls) == 2


def test_a_failed_read_is_never_stored_as_an_empty_agenda(provider):
    provider.fail = True
    _, errors = read(start_time=NOW, end_time=NOW + timedelta(days=7))
    provider.fail = False

    result = read(start_time=NOW, end_time=NOW + timedelta(days=7))

    assert errors and "Google fora do ar" in errors[0]
    assert titles(result) == ["e1", "e2"]
    assert len(provider.calls) == 2


def test_each_account_has_its_own_entry(provider):
    other = {**ACCOUNT, "id": "a2", "refresh_token": "rt-2"}

    run(cs.fetch_account_events_with_errors([ACCOUNT, other], [], start_time=NOW, end_time=NOW + timedelta(days=7)))
    run(cs.fetch_account_events_with_errors([ACCOUNT, other], [], start_time=NOW, end_time=NOW + timedelta(days=7)))

    assert len(provider.calls) == 2  # uma por conta, so na primeira vez


def test_events_come_back_tagged_by_account_and_copies_do_not_dirty_the_store(provider):
    first, _ = read(start_time=NOW, end_time=NOW + timedelta(days=7))
    first[0].notified_15 = True
    first[0].title = "alterado por quem recebeu"

    second, _ = read(start_time=NOW, end_time=NOW + timedelta(days=7))

    assert second[0].id == "google:a1:e1"
    assert second[0].notified_15 is False
    assert second[0].title == "e1"


def test_a_read_cut_at_the_limit_only_serves_the_same_start(provider):
    many = Provider([ev(f"x{i}", NOW + timedelta(hours=i + 1)) for i in range(6)])
    cs_fetch = many.fetch

    async def limited(config, **kw):
        return await cs_fetch(config, **kw)

    import app.services.calendar_service as module

    module.fetch_google_events = limited
    try:
        run(cs.fetch_account_events_with_errors([ACCOUNT], [], start_time=NOW, end_time=NOW + timedelta(days=1), max_results=3))
        again = run(cs.fetch_account_events_with_errors([ACCOUNT], [], start_time=NOW, end_time=NOW + timedelta(days=1), max_results=3))
        later = run(cs.fetch_account_events_with_errors([ACCOUNT], [], start_time=NOW + timedelta(hours=3), end_time=NOW + timedelta(days=1), max_results=3))
        bigger = run(cs.fetch_account_events_with_errors([ACCOUNT], [], start_time=NOW, end_time=NOW + timedelta(days=1), max_results=6))
    finally:
        module.fetch_google_events = many.fetch

    # Mesma pergunta: do guardado. Comecando depois ou pedindo mais: o guardado, cortado no teto,
    # pode ter deixado eventos de fora, entao vai ao provedor.
    assert len(many.calls) == 3
    assert [e.title for e in again[0]] == ["x0", "x1", "x2"]
    assert [e.title for e in later[0]] == ["x2", "x3", "x4"]
    assert len(bigger[0]) == 6


def test_creating_an_event_invalidates_the_account(provider, monkeypatch):
    read(start_time=NOW, end_time=NOW + timedelta(days=7))

    async def token(*args):
        return "tok"

    class Resp:
        is_error = False

        def json(self):
            return {"id": "novo", "summary": "Reuniao"}

    class Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw): return Resp()

    monkeypatch.setattr(cs, "_get_google_access_token", token)
    monkeypatch.setattr(cs.httpx, "AsyncClient", Client)

    run(cs.create_google_account_event(ACCOUNT, title="Reuniao", start_time=NOW, end_time=NOW + timedelta(hours=1),
                                       timezone_name="UTC"))
    read(start_time=NOW, end_time=NOW + timedelta(days=7))

    assert len(provider.calls) == 2  # a leitura depois de criar nao aproveitou o guardado


# --- Redis compartilhado -------------------------------------------------------------------


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttls[key] = ex

    async def delete(self, key):
        self.data.pop(key, None)


def test_another_process_sees_what_this_one_stored_through_redis(provider, monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(calendar_cache, "get_redis_client", lambda: redis)

    read(start_time=NOW, end_time=NOW + timedelta(days=7))
    calendar_cache.clear_memory()  # "outro processo": sem memoria propria

    other = read(start_time=NOW, end_time=NOW + timedelta(days=7))

    assert len(provider.calls) == 1
    assert titles(other) == ["e1", "e2"]
    key = next(iter(redis.data))
    assert key.startswith("calendar:events:") and "rt-1" not in key  # a credencial nao vai na chave
    assert "rt-1" not in redis.data[key]
    assert redis.ttls[key] >= 60


def test_a_broken_redis_does_not_break_the_read(provider, monkeypatch):
    class Broken(FakeRedis):
        async def get(self, key):
            raise ConnectionError("redis caiu")

        async def set(self, key, value, ex=None):
            raise ConnectionError("redis caiu")

    monkeypatch.setattr(calendar_cache, "get_redis_client", lambda: Broken())

    result = read(start_time=NOW, end_time=NOW + timedelta(days=7))

    assert titles(result) == ["e1", "e2"]


# --- token de acesso ---------------------------------------------------------------------------


class TokenServer:
    def __init__(self, expires_in=3600):
        self.calls = 0
        self.expires_in = expires_in

    def client(self):
        server = self

        class Resp:
            def json(self):
                return {"access_token": f"tok-{server.calls}", "expires_in": server.expires_in}

        class Client:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def post(self, url, **kw):
                server.calls += 1
                return Resp()

        return Client


def test_google_access_token_is_reused_until_it_is_about_to_expire(monkeypatch):
    server = TokenServer(expires_in=3600)
    monkeypatch.setattr(cs.httpx, "AsyncClient", server.client())

    first = run(cs._get_google_access_token("cid", "sec", "rt-1"))
    second = run(cs._get_google_access_token("cid", "sec", "rt-1"))
    other_account = run(cs._get_google_access_token("cid", "sec", "rt-2"))

    assert first == second == "tok-1"
    assert other_account == "tok-2"
    assert server.calls == 2


def test_a_token_that_is_about_to_expire_is_not_kept(monkeypatch):
    server = TokenServer(expires_in=60)  # menos que a folga de seguranca
    monkeypatch.setattr(cs.httpx, "AsyncClient", server.client())

    run(cs._get_google_access_token("cid", "sec", "rt-1"))
    run(cs._get_google_access_token("cid", "sec", "rt-1"))

    assert server.calls == 2


def test_microsoft_access_token_is_reused_too(monkeypatch):
    server = TokenServer()
    monkeypatch.setattr(cs.httpx, "AsyncClient", server.client())

    run(cs._get_ms_access_token("cid", "sec", "common", "rt-1"))
    run(cs._get_ms_access_token("cid", "sec", "common", "rt-1"))

    assert server.calls == 1


# --- orquestrador no armazenamento comum ---------------------------------------------------------


def test_orchestrator_connects_the_shared_redis_and_survives_without_it(monkeypatch):
    from app.core import redis_client
    from services.orchestrator import main as orchestrator

    created = {}

    class Conn:
        async def ping(self):
            created["pinged"] = True

    import redis.asyncio as redis_asyncio

    monkeypatch.setattr(redis_asyncio, "from_url", lambda url, **kw: Conn())
    monkeypatch.setattr(orchestrator.settings, "redis_url", "redis:6379/0")
    redis_client.set_client(None)

    run(orchestrator._connect_shared_cache())

    assert created["pinged"] is True
    assert redis_client.get_client() is not None

    class Down:
        async def ping(self):
            raise ConnectionError("sem redis")

    monkeypatch.setattr(redis_asyncio, "from_url", lambda url, **kw: Down())
    redis_client.set_client(None)

    run(orchestrator._connect_shared_cache())  # nao levanta

    assert redis_client.get_client() is None
