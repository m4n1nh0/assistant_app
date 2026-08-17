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
from ..services.calendar_service import fetch_all_account_events
from ..services.notification_service import send_notification, build_event_message
from ..services.runtime_config_service import load_notif_config

scheduler = AsyncIOScheduler(timezone="UTC")

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
        [account for account in microsoft_accounts if account.get("refresh_token")],
    )


async def _sync_user(user_id: str):
    google_accounts, microsoft_accounts = await _load_calendar_accounts(user_id)

    notif_cfg = await load_notif_config(user_id=user_id)

    try:
        events = await fetch_all_account_events(google_accounts, microsoft_accounts)
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
    scheduler.add_job(
        _sync_and_notify,
        trigger=IntervalTrigger(minutes=5),
        id="calendar_sync",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
    logger.info("Scheduler started - calendar sync every 5 min")


def stop_scheduler():
    scheduler.shutdown(wait=False)
