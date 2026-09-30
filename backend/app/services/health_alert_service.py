"""Opt-in operational mail, independent of public health requests."""

import time

from loguru import logger

from ..core.config import get_settings
from .registration_invite_service import (
    registration_delivery_configured, send_transactional_email,
)
from .system_health_service import collect_health


class HealthAlerts:
    """Track incidents per process; delivery failures respect the cooldown too."""

    def __init__(self):
        self.failures = {}
        self.notified = set()
        self.last_attempt = None

    async def poll(self):
        settings = get_settings()
        if not settings.health_alerts_enabled:
            return
        services = await collect_health()
        for name, status in services.items():
            self.failures[name] = self.failures.get(name, 0) + 1 if status["ok"] is False else 0
        failed = {
            name for name, count in self.failures.items()
            if count >= settings.health_alert_failure_threshold
        }
        recovered = {
            name for name in self.notified
            if services.get(name, {}).get("ok") is True
        }
        if not failed and not recovered:
            return
        now = time.monotonic()
        if self.last_attempt is not None and now - self.last_attempt < settings.health_alert_cooldown_seconds:
            return
        self.last_attempt = now
        if not registration_delivery_configured():
            logger.warning("Alerta de saude pendente: email administrativo nao configurado")
            return
        lines = ["Monitoramento do backend INTARQ."]
        if failed:
            lines.append("Servicos com falha persistente: " + ", ".join(sorted(failed)))
        if recovered:
            lines.append("Servicos recuperados: " + ", ".join(sorted(recovered)))
        try:
            await send_transactional_email(
                settings.registration_admin_email,
                subject="INTARQ - " + ("anomalia nos servicos" if failed else "servicos recuperados"),
                text_content="\n".join(lines),
            )
        except Exception:
            logger.warning("Falha no envio do alerta de saude; nova tentativa apos o intervalo")
            return
        self.notified.difference_update(recovered)
        self.notified.update(failed)


health_alerts = HealthAlerts()
