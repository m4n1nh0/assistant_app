from datetime import datetime

import pytz

from app.services.calendar_action_service import build_calendar_create_action


NOW = pytz.timezone("America/Sao_Paulo").localize(
    datetime(2026, 8, 5, 12, 0)
)


def build(message: str):
    return build_calendar_create_action(message, now=NOW)


def test_builds_tomorrow_event_with_default_duration_and_confirmation():
    action = build("Agende reunião com João amanhã às 14h")

    assert action is not None
    assert action["type"] == "calendar_create"
    assert action["title"] == "reunião com João"
    assert action["start_time"] == "2026-08-06T14:00:00-03:00"
    assert action["end_time"] == "2026-08-06T15:00:00-03:00"
    assert action["provider"] == "auto"
    assert action["requires_confirmation"] is True


def test_builds_google_event_with_numeric_date_and_duration():
    action = build(
        "Marque dentista dia 10/08 às 09:30 por 30 minutos no Google Calendar"
    )

    assert action is not None
    assert action["title"] == "dentista"
    assert action["provider"] == "google"
    assert action["start_time"] == "2026-08-10T09:30:00-03:00"
    assert action["end_time"] == "2026-08-10T10:00:00-03:00"


def test_builds_outlook_event_with_explicit_time_range():
    action = build(
        "Crie um evento chamado Planejamento na sexta das 14h às 15h no Outlook"
    )

    assert action is not None
    assert action["title"] == "Planejamento"
    assert action["provider"] == "microsoft"
    assert action["start_time"] == "2026-08-07T14:00:00-03:00"
    assert action["end_time"] == "2026-08-07T15:00:00-03:00"


def test_ignores_questions_negations_and_requests_without_a_time():
    assert build("Qual é minha agenda amanhã?") is None
    assert build("Não agende reunião amanhã às 14h") is None
    assert build("Agende uma reunião amanhã") is None

