"""Le e grava, no banco, a configuracao que pertence ao usuario.

Complementa `app.core.config`: la fica infraestrutura vinda do ambiente, aqui
fica preferencia de conta. Sem `user_id`, as funcoes caem para a configuracao
global e para os valores do ambiente, caminho que existe para a instalacao de
usuario unico anterior ao multiusuario.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import AsyncSessionLocal, ConfigModel, scoped_config_key
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


def _int_value(
    value: Any,
    *,
    fallback: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


async def load_notif_config(
    db: AsyncSession | None = None,
    user_id: str | None = None,
) -> NotifConfig:
    """Carrega as preferencias de notificacao de um usuario.

    Args:
        db: sessao do banco; `None` abre uma propria.
        user_id: dono da configuracao; `None` le a global com padroes do ambiente.

    Returns:
        A configuracao pronta para uso pelo envio de notificacao.
    """
    if db is None:
        async with AsyncSessionLocal() as session:
            return await load_notif_config(session, user_id=user_id)

    settings = get_settings()
    use_environment_defaults = user_id is None
    key = scoped_config_key(user_id, _KEY_NOTIF) if user_id else _KEY_NOTIF
    data = _json_value(await db.get(ConfigModel, key), {})
    if not isinstance(data, dict):
        data = {}

    telegram_token = str(
        _pick(
            data,
            "telegram_token",
            "tgToken",
            "tg_token",
            default=(
                settings.telegram_bot_token
                if use_environment_defaults
                else ""
            ),
        )
        or ""
    )
    telegram_chat_id = str(
        _pick(
            data,
            "telegram_chat_id",
            "tgChatId",
            "tg_chat_id",
            default=(
                settings.telegram_chat_id
                if use_environment_defaults
                else ""
            ),
        )
        or ""
    )
    wa_provider = str(
        _pick(
            data,
            "wa_provider",
            "waProvider",
            default=settings.wa_provider if use_environment_defaults else "callmebot",
        )
        or "callmebot"
    )
    wa_number = str(
        _pick(
            data,
            "wa_number",
            "waNumber",
            default=settings.wa_number if use_environment_defaults else "",
        )
        or ""
    )
    wa_token = str(
        _pick(
            data,
            "wa_token",
            "waToken",
            default=settings.wa_token if use_environment_defaults else "",
        )
        or ""
    )
    wa_sid = str(
        _pick(
            data,
            "wa_sid",
            "waSid",
            default=settings.wa_sid if use_environment_defaults else "",
        )
        or ""
    )

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
        reminder_minutes=_int_value(
            _pick(data, "reminder_minutes", "reminderMinutes", default=15),
            fallback=15,
            minimum=5,
            maximum=1440,
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


async def save_notif_config(
    db: AsyncSession,
    config: NotifConfig,
    user_id: str | None = None,
) -> NotifConfig:
    """Grava as preferencias de notificacao de um usuario.

    Normaliza antes de persistir: canal sem credencial e salvo como desligado, para
    nao existir configuracao que se diz habilitada e nao consegue enviar.
    """
    payload = config.model_dump()
    payload["telegram_enabled"] = config.telegram_enabled and bool(
        config.telegram_token
    )
    payload["wa_enabled"] = config.wa_enabled and bool(config.wa_number)

    value = json.dumps(payload, ensure_ascii=False)
    key = scoped_config_key(user_id, _KEY_NOTIF) if user_id else _KEY_NOTIF
    row = await db.get(ConfigModel, key)
    if row:
        row.value = value
    else:
        db.add(ConfigModel(key=key, value=value))
    await db.commit()
    return await load_notif_config(db, user_id=user_id)
