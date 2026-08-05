import asyncio
from datetime import datetime

import pytz

from app.models.schemas import CalendarEvent, LLMResponse, Message
from app.services import calendar_query_service
from app.services.calendar_query_service import (
    CalendarQueryPlan,
    CalendarQueryResult,
    build_fallback_calendar_query,
    format_calendar_query_response,
    interpret_calendar_query,
    is_calendar_query_candidate,
)


NOW = pytz.timezone("America/Sao_Paulo").localize(
    datetime(2026, 8, 5, 12, 0)
)


def run(coro):
    return asyncio.run(coro)


def test_detects_calendar_reads_without_matching_configuration_or_creation():
    assert is_calendar_query_candidate("O que tenho na agenda hoje?") is True
    assert is_calendar_query_candidate("Quando é minha próxima reunião?") is True
    assert is_calendar_query_candidate("Como configurar OAuth do Google Calendar?") is False
    assert is_calendar_query_candidate("Agende uma reunião amanhã às 14h") is False


def test_fallback_builds_tomorrow_range_in_profile_timezone():
    plan = build_fallback_calendar_query(
        "Quais são meus compromissos amanhã?",
        now=NOW,
    )

    assert plan is not None
    assert plan.start_time.isoformat() == "2026-08-06T00:00:00-03:00"
    assert plan.end_time.isoformat() == "2026-08-07T00:00:00-03:00"
    assert plan.provider == "all"
    assert plan.interpreted_by == "fallback"


def test_ai_interpreter_returns_validated_structured_plan(monkeypatch):
    async def dispatch(provider, message, history, system_prompt):
        assert provider == "gpt"
        assert message == "Estou livre amanhã depois das 14h no Google?"
        assert "Retorne somente um objeto JSON" in system_prompt
        return LLMResponse(
            llm="gpt",
            content=(
                '{"intent":"calendar_query",'
                '"start_time":"2026-08-06T14:00:00-03:00",'
                '"end_time":"2026-08-07T00:00:00-03:00",'
                '"provider":"google","search_text":null,"limit":10}'
            ),
        )

    monkeypatch.setattr(
        calendar_query_service.langchain_agent_service,
        "dispatch_single",
        dispatch,
    )

    plan = run(interpret_calendar_query(
        "Estou livre amanhã depois das 14h no Google?",
        history=[],
        timezone_name="America/Sao_Paulo",
        requested_llm="gpt",
        active_llms=["gpt"],
        now=NOW,
    ))

    assert plan is not None
    assert plan.provider == "google"
    assert plan.start_time.isoformat() == "2026-08-06T14:00:00-03:00"
    assert plan.interpreted_by == "gpt"


def test_invalid_ai_output_uses_deterministic_fallback(monkeypatch):
    async def dispatch(*args, **kwargs):
        return LLMResponse(llm="gpt", content="não é JSON")

    monkeypatch.setattr(
        calendar_query_service.langchain_agent_service,
        "dispatch_single",
        dispatch,
    )

    plan = run(interpret_calendar_query(
        "O que tenho na agenda hoje?",
        history=[],
        timezone_name="America/Sao_Paulo",
        requested_llm="gpt",
        active_llms=["gpt"],
        now=NOW,
    ))

    assert plan is not None
    assert plan.interpreted_by == "fallback"
    assert plan.start_time.isoformat() == "2026-08-05T00:00:00-03:00"


def test_ai_can_reject_a_false_positive_calendar_question(monkeypatch):
    async def dispatch(*args, **kwargs):
        return LLMResponse(
            llm="gpt",
            content=(
                '{"intent":"none","start_time":null,"end_time":null,'
                '"provider":"all","search_text":null,"limit":10}'
            ),
        )

    monkeypatch.setattr(
        calendar_query_service.langchain_agent_service,
        "dispatch_single",
        dispatch,
    )

    plan = run(interpret_calendar_query(
        "Qual é o melhor aplicativo de agenda?",
        history=[],
        timezone_name="America/Sao_Paulo",
        requested_llm="gpt",
        active_llms=["gpt"],
        now=NOW,
    ))

    assert plan is None


def test_ai_interpreter_understands_calendar_follow_up_from_history(monkeypatch):
    async def dispatch(provider, message, history, system_prompt):
        assert message == "E na sexta?"
        assert all(item.role == "user" for item in history)
        assert [item.content for item in history] == [
            "O que tenho na agenda amanhã?"
        ]
        return LLMResponse(
            llm="gpt",
            content=(
                '{"intent":"calendar_query",'
                '"start_time":"2026-08-07T00:00:00-03:00",'
                '"end_time":"2026-08-08T00:00:00-03:00",'
                '"provider":"all","search_text":null,"limit":10}'
            ),
        )

    monkeypatch.setattr(
        calendar_query_service.langchain_agent_service,
        "dispatch_single",
        dispatch,
    )

    plan = run(interpret_calendar_query(
        "E na sexta?",
        history=[
            Message(role="user", content="O que tenho na agenda amanhã?"),
            Message(role="assistant", content="Evento privado às 14h"),
        ],
        timezone_name="America/Sao_Paulo",
        requested_llm="gpt",
        active_llms=["gpt"],
        now=NOW,
    ))

    assert plan is not None
    assert plan.start_time.isoformat() == "2026-08-07T00:00:00-03:00"
    assert plan.interpreted_by == "gpt"


def test_execute_query_filters_provider_search_and_limit(monkeypatch):
    async def accounts(user_id):
        assert user_id == "user-1"
        return (
            [{"id": "g1", "refresh_token": "g", "label": "Pessoal"}],
            [{"id": "m1", "refresh_token": "m", "label": "Trabalho"}],
        )

    async def fetch(google, microsoft, **query):
        assert len(google) == 1
        assert microsoft == []
        return ([
            CalendarEvent(
                id="g1:event-1",
                title="Reunião com João",
                start_time=pytz.utc.localize(datetime(2026, 8, 6, 17, 0)),
                end_time=pytz.utc.localize(datetime(2026, 8, 6, 18, 0)),
                source="google",
            ),
            CalendarEvent(
                id="g1:event-2",
                title="Dentista",
                start_time=pytz.utc.localize(datetime(2026, 8, 6, 19, 0)),
                source="google",
            ),
            CalendarEvent(
                id="g1:event-3",
                title="Reunião com João fora do período",
                start_time=pytz.utc.localize(datetime(2026, 8, 8, 17, 0)),
                source="google",
            ),
        ], [])

    monkeypatch.setattr(calendar_query_service, "_load_user_accounts", accounts)
    monkeypatch.setattr(
        calendar_query_service,
        "fetch_account_events_with_errors",
        fetch,
    )
    plan = CalendarQueryPlan(
        start_time="2026-08-06T00:00:00-03:00",
        end_time="2026-08-07T00:00:00-03:00",
        provider="google",
        search_text="João",
        limit=1,
    )

    result = run(calendar_query_service.execute_calendar_query("user-1", plan))

    assert result.connected_accounts == 1
    assert [event.title for event in result.events] == ["Reunião com João"]


def test_formats_only_events_returned_by_calendar_provider():
    plan = CalendarQueryPlan(
        start_time="2026-08-06T00:00:00-03:00",
        end_time="2026-08-07T00:00:00-03:00",
    )
    result = CalendarQueryResult(
        connected_accounts=1,
        events=[CalendarEvent(
            id="event-1",
            title="Planejamento",
            start_time=pytz.utc.localize(datetime(2026, 8, 6, 17, 0)),
            end_time=pytz.utc.localize(datetime(2026, 8, 6, 18, 0)),
            source="google",
        )],
    )

    content = format_calendar_query_response(plan, result)

    assert "Planejamento" in content
    assert "06/08 14:00–15:00" in content
    assert "Google" in content


def test_formats_empty_and_failed_queries_differently():
    plan = CalendarQueryPlan(
        start_time="2026-08-06T00:00:00-03:00",
        end_time="2026-08-07T00:00:00-03:00",
    )

    empty = format_calendar_query_response(
        plan,
        CalendarQueryResult(connected_accounts=1),
    )
    failed = format_calendar_query_response(
        plan,
        CalendarQueryResult(connected_accounts=1, errors=["token inválido"]),
    )

    assert "não tem eventos" in empty
    assert "Não consegui consultar" in failed
