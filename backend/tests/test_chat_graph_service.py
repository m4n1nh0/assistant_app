import asyncio

from app.models.schemas import (
    LLMResponse,
    LaunchAction,
    ResponseModeEnum,
    ShortcutType,
)
from app.services import chat_graph_service


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
        )
    )


def test_chat_graph_exposes_explicit_workflow_nodes():
    nodes = set(chat_graph_service.chat_graph.get_graph().nodes)

    assert {
        "detect_action",
        "resolve_shortcut",
        "acknowledge_action",
        "dispatch_single",
        "dispatch_multi",
        "dispatch_chain",
    }.issubset(nodes)


def test_computer_action_short_circuits_llm_dispatch(monkeypatch):
    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("LLM dispatch should not run for a local action")

    monkeypatch.setattr(
        chat_graph_service.llm_service,
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


def test_single_route_chooses_provider_and_dispatches(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def pick_provider(candidates):
        assert candidates == ["llama", "gpt"]
        return "llama"

    async def dispatch(llm, message, history, system_prompt):
        assert llm == "llama"
        assert message == "Ola"
        assert history == []
        assert system_prompt == "system"
        return LLMResponse(llm=llm, content="Resposta local")

    monkeypatch.setattr(chat_graph_service, "_lookup_shortcut", no_shortcut)
    monkeypatch.setattr(chat_graph_service, "pick_auto_llm", pick_provider)
    monkeypatch.setattr(chat_graph_service.llm_service, "dispatch_single", dispatch)

    result = run_graph(active_llms=["llama", "gpt"])

    assert result["action_kind"] == "chat"
    assert result["responses"] == [
        LLMResponse(llm="llama", content="Resposta local")
    ]
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
    monkeypatch.setattr(chat_graph_service.llm_service, "dispatch_multi", dispatch)

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
    monkeypatch.setattr(chat_graph_service.llm_service, "dispatch_chain", dispatch)

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

    async def dispatch(llm, message, history, system_prompt):
        assert system_prompt == "system\nlaunch context"
        return LLMResponse(llm=llm, content="Abrindo.")

    monkeypatch.setattr(chat_graph_service, "_lookup_shortcut", find_shortcut)
    monkeypatch.setattr(chat_graph_service.llm_service, "dispatch_single", dispatch)

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
