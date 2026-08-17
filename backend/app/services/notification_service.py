import httpx
from loguru import logger
from typing import Optional, List
from ..models.schemas import NotifConfig, NotifResult, CalendarEvent


async def send_telegram(
    message: str,
    config: NotifConfig,
    event: Optional[CalendarEvent] = None,
    assistant_name: str = "Assistente",
) -> bool:
    if not config.telegram_token or not config.telegram_chat_id:
        return False
    try:
        text = f"<b>{assistant_name}</b>\n\n{message}"
        if event and config.include_link and event.meeting_url:
            text += f'\n\n🔗 <a href="{event.meeting_url}">Entrar na reunião</a>'

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{config.telegram_token}/sendMessage",
                json={
                    "chat_id": config.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
        data = resp.json()
        if not data.get("ok"):
            raise Exception(data.get("description", "Unknown error"))
        logger.info(f"Telegram sent: {message[:60]}")
        return True
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


async def send_whatsapp(message: str, config: NotifConfig) -> bool:
    if not config.wa_number:
        return False
    try:
        match config.wa_provider:
            case "callmebot":
                return await _send_callmebot(message, config)
            case "zapi":
                return await _send_zapi(message, config)
            case "twilio":
                return await _send_twilio(message, config)
            case _:
                raise Exception(f"Provedor desconhecido: {config.wa_provider}")
    except Exception as e:
        logger.error(f"WhatsApp error: {e}")
        return False


async def _send_callmebot(message: str, config: NotifConfig) -> bool:
    number = config.wa_number.replace("+", "").replace(" ", "")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": number, "text": message, "apikey": config.wa_token},
        )
    return resp.status_code == 200


async def _send_zapi(message: str, config: NotifConfig) -> bool:
    parts = config.wa_token.split(":")
    if len(parts) < 2:
        raise Exception("Z-API: formato token inválido (instance_id:token)")
    instance, token = parts[0], parts[1]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.z-api.io/instances/{instance}/token/{token}/send-text",
            json={"phone": config.wa_number, "message": message},
        )
    return resp.status_code == 200


async def _send_twilio(message: str, config: NotifConfig) -> bool:
    import base64
    auth = base64.b64encode(f"{config.wa_sid}:{config.wa_token}".encode()).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{config.wa_sid}/Messages.json",
            headers={"Authorization": f"Basic {auth}"},
            data={
                "From": "whatsapp:+14155238886",
                "To": f"whatsapp:{config.wa_number}",
                "Body": message,
            },
        )
    return resp.status_code == 201


async def send_notification(
    message: str,
    config: NotifConfig,
    channels: List[str] = ("telegram", "whatsapp"),
    event: Optional[CalendarEvent] = None,
    assistant_name: str = "Assistente",
) -> NotifResult:
    result = NotifResult()

    if "telegram" in channels and config.telegram_enabled:
        try:
            result.telegram_ok = await send_telegram(message, config, event, assistant_name)
        except Exception as e:
            result.telegram_error = str(e)

    should_wa = (
        "whatsapp" in channels and config.wa_enabled
        and (not result.telegram_ok or not config.fallback_enabled)
    )
    if should_wa:
        try:
            result.whatsapp_ok = await send_whatsapp(message, config)
        except Exception as e:
            result.whatsapp_error = str(e)

    return result


def build_event_message(
    event: CalendarEvent,
    *,
    is_15min: bool,
    reminder_minutes: int = 15,
) -> str:
    time_str = event.start_time.strftime("%H:%M")
    src_map = {"google": "📗 Google Calendar", "teams": "📘 Teams", "outlook": "📙 Outlook"}
    src = src_map.get(event.source, event.source)
    if is_15min:
        return (
            f"⏰ Em {reminder_minutes} minutos:\n\n"
            f"📅 {event.title}\n🕐 {time_str}\n📌 {src}"
        )
    return f"🔔 Começando AGORA:\n\n📅 {event.title}\n🕐 {time_str}\n📌 {src}"
