import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import health_alert_service as alerts
from app.services import system_health_service as health


def test_disabled_check_does_not_contact_service():
    probe = AsyncMock()
    result = asyncio.run(health._check(probe, configured=False))
    assert result == {"configured": False, "ok": None, "status": "disabled"}
    probe.assert_not_awaited()


def test_probe_failure_is_sanitized():
    result = asyncio.run(health._check(AsyncMock(side_effect=ValueError("secret URL"))))
    assert result["ok"] is False
    assert "secret" not in str(result)


def test_alert_threshold_cooldown_and_recovery(monkeypatch):
    settings = SimpleNamespace(
        health_alerts_enabled=True, health_alert_failure_threshold=3,
        health_alert_cooldown_seconds=60, registration_admin_email="admin@example.test",
    )
    monkeypatch.setattr(alerts, "get_settings", lambda: settings)
    monkeypatch.setattr(alerts, "registration_delivery_configured", lambda: True)
    snapshot = {"database": {"ok": False}}
    monkeypatch.setattr(alerts, "collect_health", AsyncMock(return_value=snapshot))
    send = AsyncMock()
    monkeypatch.setattr(alerts, "send_transactional_email", send)
    clock = [0]
    monkeypatch.setattr(alerts.time, "monotonic", lambda: clock[0])

    async def run():
        monitor = alerts.HealthAlerts()
        await monitor.poll()
        await monitor.poll()
        send.assert_not_awaited()
        await monitor.poll()
        assert send.await_count == 1
        await monitor.poll()
        assert send.await_count == 1
        snapshot["database"]["ok"] = True
        clock[0] = 61
        await monitor.poll()
        assert send.await_count == 2
        assert "recuperados" in send.call_args.kwargs["subject"]
        clock[0] = 122
        await monitor.poll()
        assert send.await_count == 2
        settings.health_alerts_enabled = False
        snapshot["database"]["ok"] = False
        await monitor.poll()
        assert send.await_count == 2

    asyncio.run(run())


def test_failed_email_is_throttled_and_not_marked_delivered(monkeypatch):
    monkeypatch.setattr(alerts, "get_settings", lambda: SimpleNamespace(
        health_alerts_enabled=True, health_alert_failure_threshold=1,
        health_alert_cooldown_seconds=60, registration_admin_email="admin@example.test",
    ))
    monkeypatch.setattr(alerts, "registration_delivery_configured", lambda: True)
    monkeypatch.setattr(alerts, "collect_health", AsyncMock(return_value={"redis": {"ok": False}}))
    send = AsyncMock(side_effect=RuntimeError("email offline"))
    monkeypatch.setattr(alerts, "send_transactional_email", send)

    async def run():
        monitor = alerts.HealthAlerts()
        await monitor.poll()
        await monitor.poll()
        assert send.await_count == 1
        assert monitor.notified == set()

    asyncio.run(run())
