from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import AsyncSessionLocal, ConfigModel
from ..models.schemas import NotifConfig

_KEY_NOTIF = "notif"


def _json_value(row: ConfigModel | None, fallback: Any) -> Any:
    if row is None or not row.value:
        return fallback
    try:
        return json.loads(row.value)
    except Exception:
        return fallback


def _pick(data: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def _bool_value(value: Any, fallback: bool = False) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim", "on"}
    return bool(value)


async def load_notif_config(db: AsyncSession | None = None) -> NotifConfig:
    if db is None:
        async with AsyncSessionLocal() as session:
            return await load_notif_config(session)

    settings = get_settings()
    data = _json_value(await db.get(ConfigModel, _KEY_NOTIF), {})
    if not isinstance(data, dict):
        data = {}

    telegram_token = str(
        _pick(
            data,
            "telegram_token",
            "tgToken",
            "tg_token",
            default=settings.telegram_bot_token,
        )
        or ""
    )
    telegram_chat_id = str(
        _pick(
            data,
            "telegram_chat_id",
            "tgChatId",
            "tg_chat_id",
            default=settings.telegram_chat_id,
        )
        or ""
    )
    wa_provider = str(
        _pick(data, "wa_provider", "waProvider", default=settings.wa_provider)
        or "callmebot"
    )
    wa_number = str(
        _pick(data, "wa_number", "waNumber", default=settings.wa_number) or ""
    )
    wa_token = str(
        _pick(data, "wa_token", "waToken", default=settings.wa_token) or ""
    )
    wa_sid = str(_pick(data, "wa_sid", "waSid", default=settings.wa_sid) or "")

    return NotifConfig(
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        telegram_enabled=_bool_value(
            _pick(data, "telegram_enabled", "tgEnabled", default=None),
            fallback=bool(telegram_token),
        ),
        wa_provider=wa_provider,
        wa_number=wa_number,
        wa_token=wa_token,
        wa_sid=wa_sid,
        wa_enabled=_bool_value(
            _pick(data, "wa_enabled", "waEnabled", default=None),
            fallback=bool(wa_number),
        ),
        notify_15min=_bool_value(
            _pick(data, "notify_15min", "notify15min", default=None),
            fallback=True,
        ),
        notify_on_time=_bool_value(
            _pick(data, "notify_on_time", "notifyOnTime", default=None),
            fallback=True,
        ),
        fallback_enabled=_bool_value(
            _pick(data, "fallback_enabled", "fallbackEnabled", default=None),
            fallback=True,
        ),
        include_link=_bool_value(
            _pick(data, "include_link", "includeLink", default=None),
            fallback=True,
        ),
    )


async def save_notif_config(db: AsyncSession, config: NotifConfig) -> NotifConfig:
    payload = config.model_dump()
    payload["telegram_enabled"] = config.telegram_enabled and bool(
        config.telegram_token
    )
    payload["wa_enabled"] = config.wa_enabled and bool(config.wa_number)

    value = json.dumps(payload, ensure_ascii=False)
    row = await db.get(ConfigModel, _KEY_NOTIF)
    if row:
        row.value = value
    else:
        db.add(ConfigModel(key=_KEY_NOTIF, value=value))
    await db.commit()
    return await load_notif_config(db)
