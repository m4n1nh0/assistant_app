"""MCP como fronteira de sistema: configuracao, conexao e resiliencia.

Cobre as tres camadas separadas na migracao: o parser da configuracao
(`app.mcp.config`), o cliente com cache e disjuntor (`app.mcp.client`) e a
fachada de diagnostico que as rotas consomem (`app.services.mcp_service`).
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.adapters.mcp.local import LocalMCPGateway
from app.mcp.client import CircuitBreaker, MCPClient
from app.mcp.config import parse_servers
from app.ports.mcp import MCPUnavailable
from app.services import mcp_service as service

pytestmark = pytest.mark.unit


def run(coro):
    return asyncio.run(coro)


def client(servers: str, **kwargs) -> MCPClient:
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("cache_ttl_seconds", 300.0)
    return MCPClient(servers, **kwargs)


def patch_adapter(monkeypatch, factory):
    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", factory
    )


# --- Configuracao ----------------------------------------------------------


def test_empty_config_means_no_mcp():
    assert parse_servers("") == {}
    assert client("").configured() is False
    assert run(client("").list_tools()) == []


def test_map_form_is_accepted():
    servers = parse_servers('{"fs": {"command": "npx", "args": ["-y", "srv"]}}')

    assert list(servers) == ["fs"]
    assert servers["fs"].options["command"] == "npx"


def test_list_form_is_normalised_to_a_map():
    servers = parse_servers('[{"name": "docs", "url": "http://localhost:3000/mcp"}]')

    assert list(servers) == ["docs"]
    assert servers["docs"].options["url"] == "http://localhost:3000/mcp"


def test_stdio_transport_is_inferred_from_command():
    assert parse_servers('{"fs": {"command": "npx"}}')["fs"].transport == "stdio"


def test_http_transport_is_inferred_from_url():
    servers = parse_servers('{"docs": {"url": "http://localhost:3000/mcp"}}')

    assert servers["docs"].transport == "streamable_http"


def test_explicit_transport_is_kept():
    servers = parse_servers('{"docs": {"url": "http://x/mcp", "transport": "sse"}}')

    assert servers["docs"].transport == "sse"


def test_client_entry_carries_the_transport_back():
    entry = parse_servers('{"fs": {"command": "npx"}}')["fs"].as_client_entry()

    assert entry == {"command": "npx", "transport": "stdio"}


def test_invalid_json_degrades_to_no_servers():
    assert parse_servers("{isso nao e json}") == {}


def test_non_object_config_is_rejected():
    assert parse_servers('"apenas-uma-string"') == {}


# --- Conexao ---------------------------------------------------------------


def test_unreachable_server_returns_no_tools(monkeypatch):
    class _Client:
        def __init__(self, servers):
            pass

        async def get_tools(self):
            raise RuntimeError("connection refused")

    patch_adapter(monkeypatch, _Client)

    assert run(client('{"fs": {"command": "nao-existe"}}').list_tools()) == []


def test_failure_is_cached_to_avoid_reconnecting_every_message(monkeypatch):
    attempts = []

    class _Client:
        def __init__(self, servers):
            attempts.append(servers)

        async def get_tools(self):
            raise RuntimeError("connection refused")

    patch_adapter(monkeypatch, _Client)
    mcp = client('{"fs": {"command": "nao-existe"}}')

    run(mcp.list_tools())
    run(mcp.list_tools())

    assert len(attempts) == 1


def test_transient_failure_is_retried_with_a_ceiling(monkeypatch):
    attempts = []

    class _Client:
        def __init__(self, servers):
            attempts.append(servers)

        async def get_tools(self):
            raise RuntimeError("oscilou")

    patch_adapter(monkeypatch, _Client)
    mcp = client(
        '{"fs": {"command": "npx"}}', max_retries=2, retry_backoff=0.0
    )

    run(mcp.list_tools())

    # Tres tentativas: a primeira mais as duas repeticoes. Nunca indefinido.
    assert len(attempts) == 3


def test_tools_are_returned_and_cached(monkeypatch):
    tool = SimpleNamespace(name="read_file", description="", args_schema=None, args={})
    attempts = []

    class _Client:
        def __init__(self, servers):
            attempts.append(servers)

        async def get_tools(self):
            return [tool]

    patch_adapter(monkeypatch, _Client)
    mcp = client('{"fs": {"command": "npx"}}')

    assert [ref.name for ref in run(mcp.list_tools())] == ["read_file"]
    assert [ref.name for ref in run(mcp.list_tools())] == ["read_file"]
    assert len(attempts) == 1


def test_force_bypasses_the_cache(monkeypatch):
    attempts = []

    class _Client:
        def __init__(self, servers):
            attempts.append(servers)

        async def get_tools(self):
            return []

    patch_adapter(monkeypatch, _Client)
    mcp = client('{"fs": {"command": "npx"}}')

    run(mcp.list_tools())
    run(mcp.list_tools(force=True))

    assert len(attempts) == 2


def test_unknown_tool_is_refused_without_calling_the_server(monkeypatch):
    class _Client:
        def __init__(self, servers):
            pass

        async def get_tools(self):
            return []

    patch_adapter(monkeypatch, _Client)
    mcp = client('{"fs": {"command": "npx"}}')

    with pytest.raises(MCPUnavailable):
        run(mcp.invoke("nao_existe", {}))


# --- Disjuntor -------------------------------------------------------------


def test_circuit_opens_after_repeated_failures():
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=60.0)

    breaker.record_failure()
    assert breaker.is_open is False

    breaker.record_failure()
    assert breaker.is_open is True


def test_circuit_closes_after_a_success():
    breaker = CircuitBreaker(failure_threshold=1, reset_seconds=60.0)
    breaker.record_failure()

    breaker.record_success()

    assert breaker.is_open is False


def test_circuit_half_opens_after_the_reset_window():
    breaker = CircuitBreaker(failure_threshold=1, reset_seconds=0.01)
    breaker.record_failure()
    assert breaker.is_open is True

    import time

    time.sleep(0.02)

    # Deixa uma tentativa passar para descobrir se o servidor voltou.
    assert breaker.is_open is False


# --- Fachada de diagnostico -------------------------------------------------


def test_status_without_configuration(monkeypatch):
    monkeypatch.setattr(
        service, "get_mcp_gateway", lambda: LocalMCPGateway(client(""))
    )

    assert run(service.status()) == {
        "configured": False, "servers": [], "tools": 0
    }


def test_status_lists_servers_and_tool_names(monkeypatch):
    class _Client:
        def __init__(self, servers):
            pass

        async def get_tools(self):
            return [
                SimpleNamespace(
                    name="read_file", description="", args_schema=None, args={}
                )
            ]

    patch_adapter(monkeypatch, _Client)
    monkeypatch.setattr(
        service,
        "get_mcp_gateway",
        lambda: LocalMCPGateway(client('{"fs": {"command": "npx"}}')),
    )

    status = run(service.status())

    assert status["configured"] is True
    assert status["servers"] == ["fs"]
    assert status["tool_names"] == ["read_file"]
    assert status["detail"][0]["reachable"] is True
