import asyncio

from app.models.schemas import (
    LLMResponse,
    LaunchAction,
    ResponseModeEnum,
    ShortcutType,
)
from app.services import chat_graph_service
from app.services.calendar_query_service import CalendarQueryPlan, CalendarQueryResult


def run_graph(
    *,
    message: str = "Ola",
    mode: ResponseModeEnum = ResponseModeEnum.single,
    requested_llm: str | None = None,
    active_llms: list[str] | None = None,
):
    return asyncio.run(
        chat_graph_service.run_chat_graph(
            message=message,
            history=[],
            mode=mode,
            requested_llm=requested_llm,
            active_llms=active_llms or [],
            system_prompt="system",
            tutor_id="tutor-1",
            user_id="user-1",
        )
    )


def test_chat_graph_exposes_explicit_workflow_nodes():
    nodes = set(chat_graph_service.chat_graph.get_graph().nodes)

    assert {
        "detect_action",
        "resolve_shortcut",
        "retrieve_context",
        "acknowledge_action",
        "query_calendar",
        "dispatch_single",
        "dispatch_multi",
        "dispatch_chain",
    }.issubset(nodes)


def test_computer_action_short_circuits_llm_dispatch(monkeypatch):
    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("LLM dispatch should not run for a local action")

    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_single",
        fail_dispatch,
    )

    result = run_graph(
        message="Verifique minha rede e o meu IP",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "computer"
    assert result["action"]["action_id"] == "network_diagnostics"
    assert result["responses"][0].llm == "backend"
    assert "Diagnostico de rede" in result["responses"][0].content


def test_registration_tool_routes_structured_action_to_interface():
    result = run_graph(
        message="Cadastre o Notepad como bloco",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "registration"
    assert result["action"]["type"] == "register_shortcut"
    assert result["responses"][0].llm == "backend"
    assert "cadastrar o atalho" in result["responses"][0].content


def test_lesson_start_routes_to_education_interface_without_calling_llm(monkeypatch):
    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("LLM dispatch should not run for an interface action")

    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_single",
        fail_dispatch,
    )

    result = run_graph(
        message="Dani, vamos iniciar a aula",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "education"
    assert result["action"]["type"] == "education_open"
    assert result["action"]["destination"] == "lesson"
    assert "Modo Aula" in result["responses"][0].content


def test_calendar_action_short_circuits_llm_and_requests_confirmation(monkeypatch):
    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("LLM dispatch should not run for a calendar action")

    monkeypatch.setattr(
        chat_graph_service,
        "invoke_calendar_action_tool",
        lambda message, timezone: {
            "type": "calendar_create",
            "title": "Consulta",
            "start_time": "2026-08-10T14:00:00-03:00",
            "end_time": "2026-08-10T15:00:00-03:00",
            "timezone": timezone,
            "provider": "google",
            "requires_confirmation": True,
        },
    )
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_single",
        fail_dispatch,
    )

    result = run_graph(
        message="Agende uma consulta",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "calendar"
    assert result["action"]["requires_confirmation"] is True
    assert "10 de agosto de 2026" in result["responses"][0].content
    assert "14 horas" in result["responses"][0].content
    assert "detalhes estão prontos" in result["responses"][0].content


def test_calendar_query_uses_interpreter_and_real_events_without_chat_hallucination(
    monkeypatch,
):
    async def interpret(*args, **kwargs):
        return CalendarQueryPlan(
            start_time="2026-08-06T00:00:00-03:00",
            end_time="2026-08-07T00:00:00-03:00",
            interpreted_by="gpt",
        )

    async def execute(user_id, plan):
        assert user_id == "user-1"
        return CalendarQueryResult(
            connected_accounts=1,
            events=[],
        )

    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("Normal chat dispatch must not answer calendar data")

    monkeypatch.setattr(chat_graph_service, "interpret_calendar_query", interpret)
    monkeypatch.setattr(chat_graph_service, "execute_calendar_query", execute)
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_single",
        fail_dispatch,
    )

    result = run_graph(
        message="O que tenho na agenda amanhã?",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "calendar_query"
    assert result.get("action") is None
    assert "não tem eventos" in result["responses"][0].content


def test_single_route_chooses_provider_and_dispatches(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def pick_provider(candidates, task="general"):
        assert candidates == ["llama", "gpt"]
        assert task == "general"
        return "llama"

    async def run_with_tools(
        provider, message, history, system_prompt, tools, **kwargs
    ):
        assert provider == "llama"
        assert message == "Ola"
        assert history == []
        assert system_prompt.startswith("system")
        return LLMResponse(llm=provider, content="Resposta local"), []

    monkeypatch.setattr(chat_graph_service, "_lookup_shortcut", no_shortcut)
    monkeypatch.setattr(
        chat_graph_service.agent_service, "pick_auto_llm", pick_provider
    )
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "run_with_tools",
        run_with_tools,
    )

    result = run_graph(active_llms=["llama", "gpt"])

    assert result["action_kind"] == "chat"
    assert result["responses"] == [
        LLMResponse(llm="llama", content="Resposta local")
    ]
    assert result["agent_id"] == "general"
    assert "action" not in result


def test_multi_route_dispatches_all_active_providers(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def dispatch(llms, message, history, system_prompt):
        assert llms == ["gpt", "claude"]
        return [
            LLMResponse(llm="gpt", content="A"),
            LLMResponse(llm="claude", content="B"),
        ]

    monkeypatch.setattr(chat_graph_service, "_lookup_shortcut", no_shortcut)
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_multi",
        dispatch,
    )

    result = run_graph(
        mode=ResponseModeEnum.multi,
        active_llms=["gpt", "claude"],
    )

    assert [response.llm for response in result["responses"]] == [
        "gpt",
        "claude",
    ]


def test_chain_route_dispatches_providers_in_order(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def dispatch(llms, message, history, system_prompt):
        assert llms == ["claude", "gpt"]
        return LLMResponse(llm="gpt", content="Resposta refinada")

    monkeypatch.setattr(chat_graph_service, "_lookup_shortcut", no_shortcut)
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_chain",
        dispatch,
    )

    result = run_graph(
        mode=ResponseModeEnum.chain,
        active_llms=["claude", "gpt"],
    )

    assert result["responses"] == [
        LLMResponse(llm="gpt", content="Resposta refinada")
    ]


def test_launch_action_keeps_llm_response_and_injects_context(monkeypatch):
    launch_action = LaunchAction(
        shortcut_id="shortcut-1",
        name="Navegador",
        target="browser",
        target_type=ShortcutType.app,
    )

    async def find_shortcut(message, tutor_id):
        return launch_action, "launch", "\nlaunch context"

    async def run_with_tools(
        provider, message, history, system_prompt, tools, **kwargs
    ):
        assert "system\nlaunch context" in system_prompt
        return LLMResponse(llm=provider, content="Abrindo."), []

    monkeypatch.setattr(chat_graph_service, "_lookup_shortcut", find_shortcut)
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "run_with_tools",
        run_with_tools,
    )

    result = run_graph(
        message="Abra o navegador",
        requested_llm="gpt",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "launch"
    assert result["action"] == launch_action
    assert result["responses"][0].content == "Abrindo."


def test_empty_provider_list_returns_controlled_error(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    monkeypatch.setattr(chat_graph_service, "_lookup_shortcut", no_shortcut)

    result = run_graph()

    assert result["responses"][0].llm == "backend"
    assert result["responses"][0].is_error is True
    assert "Nenhum agente de IA" in result["responses"][0].content


def test_unexpected_graph_failure_returns_controlled_error(monkeypatch):
    async def fail_graph(_state):
        raise RuntimeError("provider connection failed")

    monkeypatch.setattr(chat_graph_service.chat_graph, "ainvoke", fail_graph)

    result = run_graph(
        requested_llm="gpt",
        active_llms=["gpt"],
    )

    assert result["action"] is None
    assert result["responses"][0].llm == "gpt"
    assert result["responses"][0].is_error is True
    assert "Tente novamente" in result["responses"][0].content
