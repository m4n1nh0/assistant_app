from datetime import datetime, timezone

from app.models.schemas import CalendarEvent, NotifConfig
from app.services.notification_service import (
    _telegram_error_message,
    _telegram_text,
    build_event_message,
)


def test_event_message_uses_configured_reminder_minutes():
    event = CalendarEvent(
        id="event-1",
        title="Aula de Banco de Dados",
        start_time=datetime(2026, 8, 17, 22, 0, tzinfo=timezone.utc),
        source="google",
    )

    message = build_event_message(
        event,
        is_15min=True,
        reminder_minutes=30,
    )

    assert "Em 30 minutos" in message
    assert "Aula de Banco de Dados" in message


def test_telegram_errors_explain_invalid_token_and_missing_chat():
    assert "Token do bot invalido" in _telegram_error_message(401, "Unauthorized")
    assert "/start" in _telegram_error_message(400, "Bad Request: chat not found")


def test_telegram_html_escapes_dynamic_content_and_preserves_safe_link():
    event = CalendarEvent(
        id="event-1",
        title="Aula",
        start_time=datetime(2026, 8, 17, 22, 0, tzinfo=timezone.utc),
        source="google",
        meeting_url='https://meet.test/?a=1&b="2"',
    )

    text = _telegram_text(
        "Revisar A < B & C > D",
        NotifConfig(include_link=True),
        event,
        "Dani & Assistente",
    )

    assert "<b>Dani &amp; Assistente</b>" in text
    assert "A &lt; B &amp; C &gt; D" in text
    assert 'href="https://meet.test/?a=1&amp;b=&quot;2&quot;"' in text
