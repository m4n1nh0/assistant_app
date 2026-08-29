"""Especialistas, ferramentas por escopo e transferencia entre agentes.

Nenhum teste aqui sobe servidor MCP nem tool-service: o agente conversa com o
`ToolGateway`, e o teste injeta um gateway fake. Se algum destes testes passar a
precisar de infraestrutura, a inversao de dependencia foi perdida.
"""

import asyncio
from types import SimpleNamespace

import pytest

from langchain_core.messages import AIMessage, SystemMessage

from app.adapters.container import build_local_tool_gateway
from app.adapters.fakes import FakeMCPGateway, FakeToolGateway
from app.models.schemas import LLMResponse
from app.services import agent_service as service

pytestmark = pytest.mark.integration


def run(coro):
    return asyncio.run(coro)


def local_gateway(monkeypatch, *, mcp: FakeMCPGateway | None = None):
    """Catalogo real do projeto, com MCP simulado."""
    gateway = build_local_tool_gateway(mcp=mcp or FakeMCPGateway(available=False))
    monkeypatch.setattr(service, "get_tool_gateway", lambda: gateway)
    return gateway


def fake_provider(monkeypatch, provider: str = "llama"):
    async def _rank(candidates, task="general", available_only=False):
        return [provider]

    monkeypatch.setattr(service, "rank_auto_llms", _rank)


def _system_prompt(messages) -> str:
    return "\n".join(
        str(item.content) for item in messages if isinstance(item, SystemMessage)
    )


def scripted_models(monkeypatch, script):
    """Cada item de `script` responde a uma visita ao no `agent` do subgrafo."""
    calls = []

    async def _invoke(provider, messages, tools=()):
        index = min(len(calls), len(script) - 1)
        calls.append({
            "provider": provider,
            "tools": sorted(tool.name for tool in tools),
            "system_prompt": _system_prompt(messages),
        })
        return script[index]

    monkeypatch.setattr(service.langchain_agent_service, "invoke_model", _invoke)
    return calls


def answer(content: str, *, provider: str = "llama", is_error: bool = False):
    """Uma rodada em que o modelo responde em texto, sem chamar ferramenta."""
    return (
        AIMessage(content=content),
        LLMResponse(llm=provider, content=content, is_error=is_error),
    )


def handoff(agent: str, reason: str = "", *, provider: str = "llama"):
    """Uma rodada em que o modelo pede transferencia."""
    message = AIMessage(
        content="",
        tool_calls=[{
            "name": service.HANDOFF_TOOL_NAME,
            "args": {"agent": agent, "reason": reason},
            "id": f"call_{agent}",
        }],
    )
    return message, LLMResponse(llm=provider, content="")


# --- Selecao de especialista -----------------------------------------------


def test_task_maps_to_specialist():
    assert service.select_specialist("code").id == "code"
    assert service.select_specialist("study").id == "study"
    assert service.select_specialist("calendar").id == "calendar"


def test_unknown_task_falls_back_to_generalist():
    assert service.select_specialist("qualquer-coisa").id == "general"


# --- Ferramentas -----------------------------------------------------------


def test_specialist_only_gets_its_own_tools(monkeypatch):
    local_gateway(monkeypatch)

    tools = run(service.build_tools(
        service.SPECIALISTS["calendar"], allow_handoff=False
    ))

    assert [tool.name for tool in tools] == ["propose_calendar_event"]


def test_handoff_tool_is_added_when_allowed(monkeypatch):
    local_gateway(monkeypatch)

    tools = run(service.build_tools(
        service.SPECIALISTS["code"], allow_handoff=True
    ))

    assert service.HANDOFF_TOOL_NAME in [tool.name for tool in tools]


def test_handoff_tool_lists_the_other_agents(monkeypatch):
    local_gateway(monkeypatch)

    tools = run(service.build_tools(
        service.SPECIALISTS["code"], allow_handoff=True
    ))
    transfer = next(t for t in tools if t.name == service.HANDOFF_TOOL_NAME)

    assert "study" in transfer.description
    assert "calendar" in transfer.description
    # O agente nao deve poder transferir para si mesmo.
    assert "code (" not in transfer.description


def test_tool_catalog_failure_does_not_break_the_agent(monkeypatch):
    class _Broken(FakeToolGateway):
        async def list_tools(self, *, agent_id=""):
            raise RuntimeError("catalogo fora do ar")

    monkeypatch.setattr(service, "get_tool_gateway", lambda: _Broken())

    tools = run(service.build_tools(
        service.SPECIALISTS["general"], allow_handoff=False
    ))

    assert tools == []


def test_mcp_failure_does_not_break_tool_building(monkeypatch):
    local_gateway(monkeypatch, mcp=FakeMCPGateway(available=False))

    tools = run(service.build_tools(
        service.SPECIALISTS["general"], allow_handoff=False
    ))

    assert tools == []


def test_mcp_tools_reach_specialists_that_use_them(monkeypatch):
    mcp = FakeMCPGateway()
    mcp.add("mcp_read_file", server="fs")
    local_gateway(monkeypatch, mcp=mcp)

    tools = run(service.build_tools(
        service.SPECIALISTS["general"], allow_handoff=False
    ))
    assert "mcp_read_file" in [tool.name for tool in tools]

    # O agente de estudos nao usa MCP; suas ferramentas nao devem incluir isso.
    study = run(service.build_tools(
        service.SPECIALISTS["study"], allow_handoff=False
    ))
    assert study == []


def test_mcp_tool_keeps_its_origin_in_the_metadata(monkeypatch):
    """MCP e origem registrada, nao um tipo diferente de tool calling."""
    mcp = FakeMCPGateway()
    mcp.add("mcp_read_file", server="fs")
    local_gateway(monkeypatch, mcp=mcp)

    tools = run(service.build_tools(
        service.SPECIALISTS["general"], allow_handoff=False
    ))
    tool = next(item for item in tools if item.name == "mcp_read_file")

    assert tool.metadata["source"] == "mcp"
    assert tool.metadata["server"] == "fs"


# --- Execucao e transferencia ----------------------------------------------


def test_answer_without_handoff_stays_with_the_first_agent(monkeypatch):
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    scripted_models(monkeypatch, [answer("pronto")])

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
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    scripted_models(monkeypatch, [
        handoff("code", "e sobre python"),
        answer("resposta de codigo"),
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


def test_handoff_appears_in_the_tool_trace(monkeypatch):
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    scripted_models(monkeypatch, [handoff("code"), answer("ok")])

    outcome = run(service.run_agents(
        message="me ajuda",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama"],
    ))

    trace = [entry["tool"] for entry in outcome.tool_trace]
    assert service.HANDOFF_TOOL_NAME in trace


def test_handoff_to_unknown_agent_is_ignored(monkeypatch):
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    scripted_models(monkeypatch, [handoff("inexistente")])

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
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    scripted_models(monkeypatch, [
        handoff("code"),
        handoff("general"),
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
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    monkeypatch.setattr(
        service, "settings",
        SimpleNamespace(agent_max_handoffs=0, agent_max_tool_iterations=3),
    )
    calls = scripted_models(monkeypatch, [answer("resposta")])

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
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    calls = scripted_models(monkeypatch, [answer("ok")])

    run(service.run_agents(
        message="erro no meu python",
        history=[],
        system_prompt="system",
        task="code",
        active_llms=["llama"],
    ))

    assert "system" in calls[0]["system_prompt"]
    assert "agente de codigo" in calls[0]["system_prompt"]


def test_handoff_swaps_the_instructions_of_the_new_agent(monkeypatch):
    local_gateway(monkeypatch)
    fake_provider(monkeypatch)
    calls = scripted_models(monkeypatch, [
        handoff("calendar", "e agenda"),
        answer("marcado"),
    ])

    run(service.run_agents(
        message="marque reuniao",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["llama"],
    ))

    assert "agente generalista" in calls[0]["system_prompt"]
    # O especialista que assume nao pode herdar a instrucao do anterior.
    assert "agente de agenda" in calls[1]["system_prompt"]
    assert "agente generalista" not in calls[1]["system_prompt"]


def test_requested_provider_overrides_the_router(monkeypatch):
    local_gateway(monkeypatch)

    async def _rank(candidates, task="general", available_only=False):
        raise AssertionError("roteador nao deve ser consultado")

    monkeypatch.setattr(service, "rank_auto_llms", _rank)
    calls = scripted_models(monkeypatch, [answer("ok", provider="claude")])

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
    local_gateway(monkeypatch)

    async def _rank(candidates, task="general", available_only=False):
        return []

    monkeypatch.setattr(service, "rank_auto_llms", _rank)

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=[],
    ))

    assert outcome.response.is_error is True
    assert "Nenhum agente" in outcome.response.content


def test_automatic_agent_falls_back_until_local_provider_answers(monkeypatch):
    local_gateway(monkeypatch)

    async def _rank(candidates, task="general", available_only=False):
        assert available_only is True
        return ["claude", "localai"]

    monkeypatch.setattr(service, "rank_auto_llms", _rank)
    calls = scripted_models(monkeypatch, [
        answer("sem saldo", provider="claude", is_error=True),
        answer("resposta local", provider="localai"),
    ])

    outcome = run(service.run_agents(
        message="explique este erro de codigo",
        history=[],
        system_prompt="system",
        task="code",
        active_llms=["claude", "localai"],
    ))

    assert [call["provider"] for call in calls] == ["claude", "localai"]
    assert outcome.provider == "localai"
    assert outcome.response.content == "resposta local"


def test_requested_provider_does_not_fall_back(monkeypatch):
    """Provedor escolhido na interface falha visivelmente em vez de ser trocado."""
    local_gateway(monkeypatch)
    calls = scripted_models(
        monkeypatch, [answer("sem saldo", provider="claude", is_error=True)]
    )

    outcome = run(service.run_agents(
        message="oi",
        history=[],
        system_prompt="system",
        task="general",
        active_llms=["claude", "localai"],
        requested_llm="claude",
    ))

    assert [call["provider"] for call in calls] == ["claude"]
    assert outcome.response.is_error is True


# --- Estrutura do subgrafo --------------------------------------------------


def test_agent_subgraph_exposes_explicit_nodes():
    """O ciclo do agente e grafo, nao laco: os nos precisam existir de fato."""
    nodes = set(service.agent_graph.get_graph().nodes)

    assert {"agent", "tools", "handoff", "finalize"} <= nodes
