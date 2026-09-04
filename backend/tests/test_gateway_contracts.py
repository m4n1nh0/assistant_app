"""Testes de contrato: as implementacoes local e remota devem ser trocaveis.

A arquitetura promete que mover o catalogo de ferramentas ou o MCP para outro
processo e mudanca de configuracao, nao de comportamento. Uma promessa dessas
so vale se algo a verificar - senao as duas implementacoes divergem devagar ate
que trocar o transporte vire uma migracao.

Cada teste aqui roda a **mesma** asserção contra os dois gateways. O remoto fala
com um `httpx.AsyncClient` apontado para o entrypoint real do servico, entao o
contrato exercitado e o HTTP de verdade, sem simular resposta.
"""

import asyncio

import httpx
import pytest

from app.adapters.container import build_local_tool_gateway
from app.adapters.fakes import FakeMCPGateway
from app.adapters.mcp.local import LocalMCPGateway
from app.adapters.mcp.remote import RemoteMCPGateway
from app.adapters.tools.remote import RemoteToolGateway
from app.core.observability import configure_sink, default_sink
from app.mcp.client import MCPClient
from app.ports.tools import ToolInvocation

pytestmark = pytest.mark.contract


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def telemetry():
    sink, memory = default_sink()
    configure_sink(sink, memory=memory)
    yield
    memory.clear()


def asgi_client(app) -> httpx.AsyncClient:
    """Cliente que fala com a aplicacao em memoria, sem abrir porta."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://contract"
    )


# --- Tool Gateway -----------------------------------------------------------


def tool_gateways(monkeypatch, mcp=None):
    """Os dois gateways de ferramenta apontando para o mesmo catalogo."""
    from services.tool_service import main as tool_service

    local = build_local_tool_gateway(mcp=mcp or FakeMCPGateway(available=False))
    monkeypatch.setattr(tool_service, "gateway", local)
    remote = RemoteToolGateway(
        "http://contract", client=asgi_client(tool_service.app), max_retries=0
    )
    return local, remote


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_catalog_is_the_same_through_both_transports(monkeypatch, index):
    gateways = tool_gateways(monkeypatch)
    names = [item.name for item in run(gateways[index].list_tools())]

    assert "propose_calendar_event" in names
    assert "propose_coding_action" in names


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_scope_is_enforced_through_both_transports(monkeypatch, index):
    gateways = tool_gateways(monkeypatch)

    names = [item.name for item in run(gateways[index].list_tools(agent_id="calendar"))]

    assert names == ["propose_calendar_event"]


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_successful_invocation_matches(monkeypatch, index):
    gateways = tool_gateways(monkeypatch)

    result = run(
        gateways[index].invoke(
            ToolInvocation(
                name="propose_project_action",
                args={"request": "abrir o projeto no vscode"},
                agent_id="code",
            )
        )
    )

    assert result.ok is True
    assert result.name == "propose_project_action"


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_unknown_tool_fails_the_same_way(monkeypatch, index):
    gateways = tool_gateways(monkeypatch)

    result = run(gateways[index].invoke(ToolInvocation(name="fantasma")))

    assert result.ok is False
    assert "desconhecida" in result.error


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_scope_violation_fails_the_same_way(monkeypatch, index):
    gateways = tool_gateways(monkeypatch)

    result = run(
        gateways[index].invoke(
            ToolInvocation(
                name="propose_calendar_event",
                args={"request": "reuniao amanha"},
                agent_id="code",
            )
        )
    )

    assert result.ok is False
    assert "nao esta liberada" in result.error


def test_remote_tool_gateway_degrades_when_the_service_is_down():
    """Catalogo inalcancavel devolve lista vazia, e o agente responde sem tool."""
    gateway = RemoteToolGateway("http://127.0.0.1:9", max_retries=0, timeout_seconds=0.2)

    assert run(gateway.list_tools()) == []

    result = run(gateway.invoke(ToolInvocation(name="qualquer")))
    assert result.ok is False
    assert "indisponivel" in result.error


# --- MCP Gateway ------------------------------------------------------------


class _StubMCP:
    """Servidor MCP simulado no nivel do adaptador, sem processo externo."""

    def __init__(self, servers):
        self.servers = servers

    async def get_tools(self):
        from types import SimpleNamespace

        async def _run(args):
            return "conteudo do arquivo"

        return [
            SimpleNamespace(
                name="read_file",
                description="le um arquivo",
                args_schema={"type": "object", "properties": {}},
                args={},
                metadata={"server_name": "fs"},
                ainvoke=_run,
            )
        ]


def mcp_gateways(monkeypatch):
    """Os dois gateways de MCP sobre o mesmo cliente."""
    from services.mcp_service import main as mcp_service

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _StubMCP
    )
    client = MCPClient('{"fs": {"command": "npx"}}', max_retries=0)
    monkeypatch.setattr(mcp_service, "client", client)
    local = LocalMCPGateway(client)
    remote = RemoteMCPGateway(
        "http://contract", client=asgi_client(mcp_service.app), max_retries=0
    )
    return local, remote


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_mcp_tools_are_listed_the_same_way(monkeypatch, index):
    gateways = mcp_gateways(monkeypatch)

    refs = run(gateways[index].list_tools())

    assert [ref.name for ref in refs] == ["read_file"]
    assert refs[0].server == "fs"


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_mcp_invocation_matches(monkeypatch, index):
    gateways = mcp_gateways(monkeypatch)

    assert run(gateways[index].invoke("read_file", {})) == "conteudo do arquivo"


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_mcp_health_reports_the_server(monkeypatch, index):
    gateways = mcp_gateways(monkeypatch)

    health = run(gateways[index].health())

    assert [item.name for item in health] == ["fs"]
    assert health[0].reachable is True


def test_remote_mcp_gateway_reports_an_unreachable_service():
    gateway = RemoteMCPGateway(
        "http://127.0.0.1:9", max_retries=0, timeout_seconds=0.2
    )

    assert run(gateway.list_tools()) == []
    health = run(gateway.health())
    assert health[0].reachable is False
    # Depois de descobrir que nao ha servico, o gateway para de anunciar MCP.
    assert gateway.configured() is False
