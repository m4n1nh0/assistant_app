from datetime import datetime, timezone

from app.models.schemas import CalendarEvent
from app.services.notification_service import build_event_message


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
