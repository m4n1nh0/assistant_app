"""Envio de notificacao por Telegram e WhatsApp, com fallback entre canais.

O erro de cada canal e traduzido para uma frase acionavel antes de subir - a
mensagem original costuma trazer token ou URL, que nao podem aparecer na tela.
"""

import httpx
from html import escape
from loguru import logger
from typing import Optional, List
from ..models.schemas import NotifConfig, NotifResult, CalendarEvent


def _telegram_error_message(status_code: int, description: str) -> str:
    """Traduz erros conhecidos sem devolver token ou URL sensivel."""

    detail = description.strip()
    lowered = detail.lower()
    if status_code == 401 or "unauthorized" in lowered:
        return "Token do bot invalido. Gere ou copie novamente o token no BotFather."
    if "chat not found" in lowered:
        return (
            "Chat ID nao encontrado. Abra a conversa com o bot no Telegram, "
            "envie /start e confira o Chat ID."
        )
    if status_code == 403 or "bot was blocked" in lowered:
        return "O bot foi bloqueado ou nao tem permissao para enviar a esse chat."
    if status_code == 429 or "too many requests" in lowered:
        return (
            "O Telegram limitou os envios. Aguarde alguns instantes e "
            "tente novamente."
        )
    if "can't parse entities" in lowered:
        return "O Telegram recusou a formatacao da mensagem."
    if detail:
        return f"Telegram recusou o envio: {detail}"
    return f"Telegram recusou o envio (HTTP {status_code})."


def _telegram_text(
    message: str,
    config: NotifConfig,
    event: Optional[CalendarEvent],
    assistant_name: str,
) -> str:
    text = f"<b>{escape(assistant_name)}</b>\n\n{escape(message)}"
    if event and config.include_link and event.meeting_url:
        safe_url = escape(event.meeting_url, quote=True)
        text += f'\n\n🔗 <a href="{safe_url}">Entrar na reunião</a>'
    return text


async def _deliver_telegram(
    message: str,
    config: NotifConfig,
    event: Optional[CalendarEvent] = None,
    assistant_name: str = "Assistant",
) -> tuple[bool, str]:
    if not config.telegram_token or not config.telegram_chat_id:
        return False, "Preencha o token do bot e o Chat ID."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{config.telegram_token}/sendMessage",
                json={
                    "chat_id": config.telegram_chat_id,
                    "text": _telegram_text(message, config, event, assistant_name),
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
        try:
            data = resp.json()
        except ValueError:
            return False, f"Resposta invalida do Telegram (HTTP {resp.status_code})."
        if not data.get("ok"):
            return False, _telegram_error_message(
                resp.status_code,
                str(data.get("description", "")),
            )
        return True, "Telegram conectado e mensagem de teste enviada."
    except httpx.TimeoutException:
        return False, "O Telegram demorou para responder. Tente novamente."
    except httpx.HTTPError:
        return False, "Nao foi possivel conectar ao Telegram a partir do backend."
    except Exception:
        return False, "Falha inesperada ao enviar a mensagem pelo Telegram."


async def send_telegram(
    message: str,
    config: NotifConfig,
    event: Optional[CalendarEvent] = None,
    assistant_name: str = "Assistant",
) -> bool:
    """Envia a mensagem pelo bot do Telegram configurado."""
    ok, message_or_error = await _deliver_telegram(
        message,
        config,
        event,
        assistant_name,
    )
    if ok:
        logger.info(f"Telegram sent: {message[:60]}")
        return True
    logger.error("Telegram error: {}", message_or_error)
    return False


async def test_telegram_connection(config: NotifConfig) -> tuple[bool, str]:
    """Testa token e chat id do Telegram sem enviar lembrete de verdade.

    Returns:
        Uma tupla `(ok, mensagem)` para exibir direto na tela de configuracao.
    """
    return await _deliver_telegram(
        "✅ Assistente conectado! Notificações ativas.",
        config,
    )


async def send_whatsapp(message: str, config: NotifConfig) -> bool:
    """Envia a mensagem pelo provedor de WhatsApp configurado."""
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
    assistant_name: str = "Assistant",
) -> NotifResult:
    """Envia por todos os canais pedidos, respeitando a regra de fallback.

    Com `fallback_enabled`, o WhatsApp so e acionado quando o Telegram falhou; sem
    ele, os dois canais recebem. Falha de canal nao levanta excecao: volta dentro do
    `NotifResult`, para um canal quebrado nao impedir o outro.

    Args:
        message: texto ja formatado.
        config: preferencias de notificacao do usuario.
        channels: canais a tentar.
        event: evento de origem, quando o aviso vem da agenda.
        assistant_name: nome da persona, usado na assinatura da mensagem.

    Returns:
        O resultado por canal, com o erro de cada um quando houver.
    """
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
    """Escreve o texto do lembrete de um evento.

    Args:
        event: evento que gerou o aviso.
        is_15min: se e o aviso antecipado ou o do horario.
        reminder_minutes: antecedencia configurada, citada no texto.

    Returns:
        A mensagem pronta para envio.
    """
    time_str = event.start_time.strftime("%H:%M")
    src_map = {"google": "📗 Google Calendar", "teams": "📘 Teams", "outlook": "📙 Outlook"}
    src = src_map.get(event.source, event.source)
    if is_15min:
        return (
            f"⏰ Em {reminder_minutes} minutos:\n\n"
            f"📅 {event.title}\n🕐 {time_str}\n📌 {src}"
        )
    return f"🔔 Começando AGORA:\n\n📅 {event.title}\n🕐 {time_str}\n📌 {src}"
