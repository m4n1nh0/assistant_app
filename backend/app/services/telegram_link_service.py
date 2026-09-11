"""Vincula uma conversa privada por /start, sem pedir o Chat ID ao usuario."""

import hashlib
import hmac
import json
import re
import secrets
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import ConfigModel, scoped_config_key
from .notification_service import _telegram_error_message
from .runtime_config_service import load_notif_config, save_notif_config


async def _call(token: str, method: str, **params):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/{method}", json=params,
            )
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise ValueError("Nao foi possivel consultar o Telegram. Tente novamente.") from None
    if not isinstance(data, dict):
        raise ValueError("O Telegram retornou uma resposta invalida.")
    if not data.get("ok"):
        if response.status_code == 409:
            raise ValueError("Este bot esta conectado a outro servico. Use a configuracao manual do Chat ID.")
        detail = str(data.get("description", "")).replace(token, "[oculto]")
        raise ValueError(_telegram_error_message(response.status_code, detail))
    return data["result"]


def _clean_token(token: str) -> str:
    token = token.strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError("Informe o token fornecido pelo BotFather, nao o @nome do bot.")
    return token


async def begin_link(db: AsyncSession, user_id: str, token: str) -> dict:
    token = _clean_token(token)
    bot = await _call(token, "getMe")
    webhook = await _call(token, "getWebhookInfo")
    if webhook.get("url"):
        raise ValueError("Este bot esta conectado a outro servico. Use a configuracao manual do Chat ID.")
    code = secrets.token_urlsafe(24)
    value = json.dumps({
        "code": code,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "expires": time.time() + 600,
    })
    key = scoped_config_key(user_id, "telegram_link")
    row = await db.get(ConfigModel, key)
    if row is None:
        db.add(ConfigModel(key=key, value=value))
    else:
        row.value = value
    await db.commit()
    return {"url": f"https://t.me/{bot['username']}?start={code}",
            "bot_username": bot["username"]}


async def confirm_link(db: AsyncSession, user_id: str, token: str) -> dict:
    token = _clean_token(token)
    row = await db.get(ConfigModel, scoped_config_key(user_id, "telegram_link"),
                       with_for_update=True)
    pending = json.loads(row.value) if row else {}
    if pending.get("expires", 0) <= time.time():
        raise ValueError("O link expirou. Clique em Conectar meu Telegram novamente.")
    if not hmac.compare_digest(pending.get("token_hash", ""),
                               hashlib.sha256(token.encode()).hexdigest()):
        raise ValueError("O token mudou. Clique em Conectar meu Telegram novamente.")
    # Sem offset: nao confirma nem descarta mensagens de outras integracoes.
    updates = await _call(token, "getUpdates", timeout=0, limit=100)
    for update in updates:
        message = update.get("message", {})
        chat = message.get("chat", {})
        sender = message.get("from", {})
        if (message.get("text") != f"/start {pending['code']}"
                or chat.get("type") != "private"
                or sender.get("is_bot") is not False
                or sender.get("id") != chat.get("id")
                or "forward_origin" in message):
            continue
        config = await load_notif_config(db, user_id=user_id)
        config.telegram_token = token
        config.telegram_chat_id = str(chat["id"])
        config.telegram_enabled = True
        await db.delete(row)
        await save_notif_config(db, config, user_id=user_id)
        return {"ok": True, "chat_id": config.telegram_chat_id,
                "message": "Telegram conectado! Sua conversa foi salva."}
    return {"ok": False, "chat_id": "",
            "message": "Abra o link, toque em Iniciar no Telegram e confirme novamente aqui."}
