"""Scheduler de calendario: sincroniza eventos e dispara notificacoes.

Roda em APScheduler sobre o proprio event loop. A cada rodada, percorre as
contas ativas, busca os eventos dos calendarios conectados de cada uma e envia
aviso 15 minutos antes e no horario do evento. As flags `notified_15` e
`notified_0` no banco, mais um cache em memoria, evitam aviso repetido.
"""

import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone, timedelta
from loguru import logger
from sqlalchemy import select

from ..core.database import (
    AsyncSessionLocal,
    ConfigModel,
    UserModel,
    scoped_config_key,
)
from ..core.config import get_settings
from ..services.calendar_service import fetch_all_account_events
from ..services.notification_service import send_notification, build_event_message
from ..services.runtime_config_service import load_notif_config
from ..services.microsoft_identity_service import hydrate_microsoft_account

# A tolerancia padrao do APScheduler e de 1 s: um event loop ocupado por uns
# segundos (leitura de PDF grande, por exemplo) faz o job ser pulado com
# "Run time ... was missed". Com folga, o job so atrasa e roda em seguida.
scheduler = AsyncIOScheduler(
    timezone="UTC",
    job_defaults={"misfire_grace_time": 120, "coalesce": True, "max_instances": 1},
)

_notified: set[str] = set()


def _json_value(row: ConfigModel | None, fallback):
    if row is None or not row.value:
        return fallback
    try:
        return json.loads(row.value)
    except Exception:
        return fallback


async def _load_account_store(db, key: str) -> list[dict]:
    data = _json_value(await db.get(ConfigModel, key), {"accounts": []})
    if isinstance(data, list):
        accounts = data
    elif isinstance(data, dict):
        accounts = data.get("accounts", [])
    else:
        accounts = []
    return [item for item in accounts if isinstance(item, dict)]


async def _load_calendar_accounts(
    user_id: str,
) -> tuple[list[dict], list[dict]]:
    async with AsyncSessionLocal() as db:
        google_accounts = await _load_account_store(
            db, scoped_config_key(user_id, "calendar_google_accounts")
        )
        microsoft_accounts = await _load_account_store(
            db, scoped_config_key(user_id, "calendar_microsoft_accounts")
        )

        google_legacy = _json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_google"),
            ),
            {},
        )
        if google_legacy.get("refresh_token"):
            google_accounts.append({
                "id": "google_legacy",
                "label": google_legacy.get("label") or "Google Calendar",
                "client_id": google_legacy.get("client_id", ""),
                "client_secret": google_legacy.get("client_secret", ""),
                "refresh_token": google_legacy.get("refresh_token", ""),
            })

        microsoft_legacy = _json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_microsoft"),
            ),
            {},
        )
        if microsoft_legacy.get("refresh_token"):
            microsoft_accounts.append({
                "id": "microsoft_legacy",
                "label": microsoft_legacy.get("label") or "Microsoft Calendar",
                "client_id": microsoft_legacy.get("client_id", ""),
                "client_secret": microsoft_legacy.get("client_secret", ""),
                "tenant_id": microsoft_legacy.get("tenant_id", "common"),
                "refresh_token": microsoft_legacy.get("refresh_token", ""),
            })

    return (
        [account for account in google_accounts if account.get("refresh_token")],
        [
            hydrated
            for account in microsoft_accounts
            if (hydrated := hydrate_microsoft_account(account)).get("refresh_token")
        ],
    )


async def _sync_user(user_id: str):
    google_accounts, microsoft_accounts = await _load_calendar_accounts(user_id)

    notif_cfg = await load_notif_config(user_id=user_id)

    try:
        # `max_age=0`: o agendador e quem le o provedor a cada ciclo e mantem o armazenamento
        # comum fresco; interface e chat aproveitam o que ele grava.
        events = await fetch_all_account_events(
            google_accounts, microsoft_accounts, max_age=0
        )
    except Exception as e:
        logger.error(f"Scheduler: calendar fetch failed: {e}")
        return

    now = datetime.now(timezone.utc)

    for event in events:
        start = event.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        reminder_minutes = notif_cfg.reminder_minutes
        key_15 = f"{user_id}:{event.id}:advance:{reminder_minutes}"
        diff_15 = (start - now).total_seconds()
        if (
            notif_cfg.notify_15min
            and 0 < diff_15 <= reminder_minutes * 60
            and key_15 not in _notified
        ):
            _notified.add(key_15)
            msg = build_event_message(
                event,
                is_15min=True,
                reminder_minutes=reminder_minutes,
            )
            await send_notification(msg, notif_cfg, event=event)
            logger.info(
                f"Sent {reminder_minutes}-min reminder: {event.title}"
            )

            try:
                from ..routers.websocket import broadcast_event_reminder
                await broadcast_event_reminder(
                    user_id,
                    event.title,
                    reminder_minutes,
                )
            except Exception:
                pass

        key_0 = f"{user_id}:{event.id}:0"
        diff_0 = (start - now).total_seconds()
        if (
            notif_cfg.notify_on_time
            and -300 < diff_0 <= 60
            and key_0 not in _notified
        ):
            _notified.add(key_0)
            msg = build_event_message(event, is_15min=False)
            await send_notification(msg, notif_cfg, event=event)
            logger.info(f"Sent on-time reminder: {event.title}")

            try:
                from ..routers.websocket import broadcast_event_reminder
                await broadcast_event_reminder(user_id, event.title, 0)
            except Exception:
                pass

    if len(_notified) > 1000:
        _notified.clear()


async def _mentorship_reminders():
    """Lembra quem ainda nao entregou uma atividade de mentoria que vence em breve."""
    from ..services import mentorship_service

    try:
        sent = await mentorship_service.send_due_reminders(AsyncSessionLocal)
        if sent:
            logger.info(f"Scheduler: {sent} lembrete(s) de atividade de mentoria")
    except Exception as exc:
        logger.error(f"Scheduler: lembretes de mentoria falharam: {exc}")


async def _sync_and_notify():
    async with AsyncSessionLocal() as db:
        users = (
            (
                await db.execute(
                    select(UserModel).where(UserModel.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
    for user in users:
        try:
            await _sync_user(user.id)
        except Exception as exc:
            logger.error(
                f"Scheduler: sync failed for user {user.id}: {exc}"
            )


def start_scheduler():
    """Registra a rotina de sincronizacao e liga o scheduler.

    Chamado pelo `lifespan` da aplicacao. Repetir a chamada nao duplica o job.
    """
    scheduler.add_job(
        _sync_and_notify,
        trigger=IntervalTrigger(minutes=get_settings().calendar_sync_interval_minutes),
        id="calendar_sync",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        _mentorship_reminders,
        trigger=IntervalTrigger(minutes=30),
        id="mentorship_reminders",
        replace_existing=True,
    )
    from ..services.health_alert_service import health_alerts

    settings = get_settings()
    if settings.health_alerts_enabled:
        scheduler.add_job(
            health_alerts.poll,
            trigger=IntervalTrigger(seconds=settings.health_alert_interval_seconds),
            id="health_alerts",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    logger.info(
        f"Scheduler started - calendar sync every {settings.calendar_sync_interval_minutes} min"
    )


def stop_scheduler():
    """Para o scheduler no encerramento da aplicacao."""
    scheduler.shutdown(wait=False)
