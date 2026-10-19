"""O monitor de saude so sonda quando ha uso real: nao acorda servico dormindo nem gera alerta falso."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers.websocket import manager
from app.services import activity_service as activity
from app.services import health_alert_service as alerts


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    activity.reset()
    monkeypatch.setattr(manager, "connection_users", {})
    yield
    activity.reset()


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(activity.time, "monotonic", lambda: now[0])
    return now


# --- o que conta como atividade ----------------------------------------------------------


def test_nobody_has_used_the_app_yet():
    assert activity.idle_seconds() is None
    assert activity.is_active(900) is False


def test_a_recent_request_counts_and_it_expires_with_the_window(clock):
    activity.touch()
    clock[0] += 899
    assert activity.is_active(900) is True
    clock[0] += 2
    assert activity.is_active(900) is False


def test_an_open_websocket_means_the_interface_is_on(clock):
    assert activity.is_active(900, connections=1) is True
    assert activity.is_active(900, connections=0) is False


@pytest.mark.parametrize(
    "path, has_credentials, expected",
    [
        ("/chat/", True, True),
        ("/calendar/events", True, True),
        ("/chat/", False, False),            # sem credencial: monitor externo, robo
        ("/health", True, False),             # o proprio health nao e uso
        ("/health/live", True, False),
        ("/internal/devices/invoke", True, False),   # chamada entre servicos
    ],
)
def test_only_authenticated_non_health_requests_count(path, has_credentials, expected):
    assert activity.counts_as_activity(path, has_credentials) is expected


# --- monitor de saude ---------------------------------------------------------------------


def settings(**overrides):
    values = dict(
        health_alerts_enabled=True,
        health_alert_only_when_active=True,
        health_alert_activity_window_seconds=900,
        health_alert_failure_threshold=3,
        health_alert_cooldown_seconds=60,
        registration_admin_email="admin@example.test",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def monitor(monkeypatch):
    probe = AsyncMock(return_value={"database": {"ok": True}})
    monkeypatch.setattr(alerts, "collect_health", probe)
    return alerts.HealthAlerts(), probe


def poll(monkeypatch, monitor, cfg):
    monkeypatch.setattr(alerts, "get_settings", lambda: cfg)
    run(monitor.poll())


def test_with_nobody_using_the_app_the_monitor_does_not_probe_anything(monkeypatch, monitor):
    instance, probe = monitor

    poll(monkeypatch, instance, settings())

    probe.assert_not_awaited()


def test_after_a_request_the_monitor_probes_again(monkeypatch, monitor, clock):
    instance, probe = monitor
    activity.touch()

    poll(monkeypatch, instance, settings())
    clock[0] += 1000  # passou da janela
    poll(monkeypatch, instance, settings())

    assert probe.await_count == 1


def test_an_open_interface_keeps_the_monitor_probing(monkeypatch, monitor):
    instance, probe = monitor
    monkeypatch.setattr(manager, "connection_users", {"s1": "u1"})

    poll(monkeypatch, instance, settings())

    assert probe.await_count == 1


def test_the_idle_rule_can_be_turned_off_to_monitor_around_the_clock(monkeypatch, monitor):
    instance, probe = monitor

    poll(monkeypatch, instance, settings(health_alert_only_when_active=False))

    assert probe.await_count == 1


def test_idle_does_not_count_as_a_failure_or_a_recovery(monkeypatch, monitor):
    instance, _ = monitor
    instance.failures["database"] = 2

    poll(monkeypatch, instance, settings())

    assert instance.failures == {"database": 2}  # nem zera nem soma: nao sondou


# --- middleware da API ---------------------------------------------------------------------


def _through_the_middleware(path, *, authorization, status):
    from app import main

    request = SimpleNamespace(
        url=SimpleNamespace(path=path),
        headers={"authorization": "Bearer x"} if authorization else {},
        method="GET",
        client=SimpleNamespace(host="127.0.0.1"),
    )

    async def call_next(_):
        return SimpleNamespace(status_code=status)

    run(main.log_requests(request, call_next))


def test_a_successful_authenticated_request_counts_as_use():
    _through_the_middleware("/chat/", authorization=True, status=200)

    assert activity.is_active(900) is True


@pytest.mark.parametrize(
    "path, authorization, status",
    [
        ("/chat/", True, 401),            # robo com Authorization falso
        ("/chat/", False, 200),           # sem credencial
        ("/health", True, 200),           # o health nao e uso
        ("/internal/devices/invoke", True, 200),
    ],
)
def test_requests_that_are_not_real_use_do_not_keep_the_monitor_alive(path, authorization, status):
    _through_the_middleware(path, authorization=authorization, status=status)

    assert activity.is_active(900) is False
