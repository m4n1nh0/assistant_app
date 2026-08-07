import asyncio
from types import SimpleNamespace

from app.models.schemas import LLMResponse
from app.services import agent_service as service


def run(coro):
    return asyncio.run(coro)


def no_mcp(monkeypatch):
    async def _tools(**kwargs):
        return []

    monkeypatch.setattr(service.mcp_service, "get_tools", _tools)


def fake_provider(monkeypatch, provider: str = "llama"):
    async def _pick(candidates, task="general"):
        return provider

    monkeypatch.setattr(service, "pick_auto_llm", _pick)


def scripted_runs(monkeypatch, scripts):
    """Cada item de `scripts` responde a uma rodada de especialista."""
    calls = []

    async def _run(provider, message, history, system_prompt, tools, **kwargs):
        index = min(len(calls), len(scripts) - 1)
        calls.append({
            "provider": provider,
            "system_prompt": system_prompt,
            "tools": [tool.name for tool in tools],
        })
        return scripts[index]

    monkeypatch.setattr(service.langchain_agent_service, "run_with_tools", _run)
    return calls


# --- Selecao de especialista -----------------------------------------------


def test_task_maps_to_specialist():
    assert service.select_specialist("code").id == "code"
    assert service.select_specialist("study").id == "study"
    assert service.select_specialist("calendar").id == "calendar"


def test_unknown_task_falls_back_to_generalist():
    assert service.select_specialist("qualquer-coisa").id == "general"


# --- Ferramentas -----------------------------------------------------------


def test_specialist_only_gets_its_own_tools(monkeypatch):
    no_mcp(monkeypatch)

    tools = run(service.build_tools(
        service.SPECIALISTS["calendar"], allow_handoff=False
    ))

    assert [tool.name for tool in tools] == ["propose_calendar_event"]


def test_handoff_tool_is_added_when_allowed(monkeypatch):
    no_mcp(monkeypatch)

    tools = run(service.build_tools(
        service.SPECIALISTS["code"], allow_handoff=True
    ))

    assert service.HANDOFF_TOOL_NAME in [tool.name for tool in tools]


def test_handoff_tool_lists_the_other_agents(monkeypatch):
    no_mcp(monkeypatch)

    tools = run(service.build_tools(
        service.SPECIALISTS["code"], allow_handoff=True
    ))
    handoff = next(t for t in tools if t.name == service.HANDOFF_TOOL_NAME)

    assert "study" in handoff.description
    assert "calendar" in handoff.description
    # O agente nao deve poder transferir para si mesmo.
    assert "code (" not in handoff.description


def test_mcp_failure_does_not_break_tool_building(monkeypatch):
    async def _boom(**kwargs):
        raise RuntimeError("servidor MCP fora do ar")

    monkeypatch.setattr(service.mcp_service, "get_tools", _boom)

    tools = run(service.build_tools(
        service.SPECIALISTS["general"], allow_handoff=False
    ))

    assert tools == []


def test_mcp_tools_reach_specialists_that_use_them(monkeypatch):
    marker = SimpleNamespace(name="mcp_read_file")

    async def _tools(**kwargs):
        return [marker]

    monkeypatch.setattr(service.mcp_service, "get_tools", _tools)

    tools = run(service.build_tools(
        service.SPECIALISTS["general"], allow_handoff=False
    ))
    assert marker in tools

    # O agente de estudos nao usa MCP; suas ferramentas nao devem incluir isso.
    study = run(service.build_tools(
        service.SPECIALISTS["study"], allow_handoff=False
    ))
    assert marker not in study


# --- Execucao e transferencia ----------------------------------------------


def test_answer_without_handoff_stays_with_the_first_agent(monkeypatch):
    no_mcp(monkeypatch)
    fake_provider(monkeypatch)
    scripted_runs(monkeypatch, [
        (LLMResponse(llm="llama", content="pronto"), []),
    ])

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama"],
    ))

    assert outcome.agent_id == "general"
    assert outcome.response.content == "pronto"
    assert outcome.handoffs == []


def test_handoff_moves_the_conversation_to_the_target_agent(monkeypatch):
    no_mcp(monkeypatch)
    fake_provider(monkeypatch)
    scripted_runs(monkeypatch, [
        (
            LLMResponse(llm="llama", content=""),
            [{
                "tool": service.HANDOFF_TOOL_NAME,
                "args": {"agent": "code", "reason": "e sobre python"},
                "stopped": True,
            }],
        ),
        (LLMResponse(llm="llama", content="resposta de codigo"), []),
    ])

    outcome = run(service.run_agents(
        message="me ajuda",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama"],
    ))

    assert outcome.agent_id == "code"
    assert outcome.response.content == "resposta de codigo"
    assert outcome.handoffs == [
        {"from": "general", "to": "code", "reason": "e sobre python"}
    ]


def test_handoff_to_unknown_agent_is_ignored(monkeypatch):
    no_mcp(monkeypatch)
    fake_provider(monkeypatch)
    scripted_runs(monkeypatch, [
        (
            LLMResponse(llm="llama", content="fico com essa"),
            [{
                "tool": service.HANDOFF_TOOL_NAME,
                "args": {"agent": "inexistente"},
                "stopped": True,
            }],
        ),
    ])

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama"],
    ))

    assert outcome.agent_id == "general"
    assert outcome.handoffs == []


def test_agent_cannot_be_visited_twice(monkeypatch):
    """Impede o pingue-pongue: general -> code -> general."""
    no_mcp(monkeypatch)
    fake_provider(monkeypatch)
    scripted_runs(monkeypatch, [
        (
            LLMResponse(llm="llama", content=""),
            [{
                "tool": service.HANDOFF_TOOL_NAME,
                "args": {"agent": "code"},
                "stopped": True,
            }],
        ),
        (
            LLMResponse(llm="llama", content="devolvendo"),
            [{
                "tool": service.HANDOFF_TOOL_NAME,
                "args": {"agent": "general"},
                "stopped": True,
            }],
        ),
    ])

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama"],
    ))

    assert outcome.agent_id == "code"
    assert len(outcome.handoffs) == 1


def test_handoff_budget_is_respected(monkeypatch):
    no_mcp(monkeypatch)
    fake_provider(monkeypatch)
    monkeypatch.setattr(
        service, "settings",
        SimpleNamespace(agent_max_handoffs=0, agent_max_tool_iterations=3),
    )
    calls = scripted_runs(monkeypatch, [
        (LLMResponse(llm="llama", content="resposta"), []),
    ])

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama"],
    ))

    # Sem orcamento de transferencia, a ferramenta nem e oferecida.
    assert service.HANDOFF_TOOL_NAME not in calls[0]["tools"]
    assert outcome.handoffs == []


def test_specialist_instructions_reach_the_prompt(monkeypatch):
    no_mcp(monkeypatch)
    fake_provider(monkeypatch)
    calls = scripted_runs(monkeypatch, [
        (LLMResponse(llm="llama", content="ok"), []),
    ])

    run(service.run_agents(
        message="erro no meu python",
        history=[],
        system_prompt="system",
        task="code",
        active_llms=["llama"],
    ))

    assert "system" in calls[0]["system_prompt"]
    assert "agente de codigo" in calls[0]["system_prompt"]


def test_requested_provider_overrides_the_router(monkeypatch):
    no_mcp(monkeypatch)

    async def _pick(candidates, task="general"):
        raise AssertionError("roteador nao deve ser consultado")

    monkeypatch.setattr(service, "pick_auto_llm", _pick)
    calls = scripted_runs(monkeypatch, [
        (LLMResponse(llm="claude", content="ok"), []),
    ])

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama", "claude"],
        requested_llm="claude",
    ))

    assert calls[0]["provider"] == "claude"
    assert outcome.provider == "claude"


def test_no_provider_available_returns_controlled_error(monkeypatch):
    no_mcp(monkeypatch)

    async def _pick(candidates, task="general"):
        return ""

    monkeypatch.setattr(service, "pick_auto_llm", _pick)

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=[],
    ))

    assert outcome.response.is_error is True
    assert "Nenhum agente" in outcome.response.content
