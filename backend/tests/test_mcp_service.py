import asyncio
from types import SimpleNamespace

import pytest

from app.services import mcp_service as service


def run(coro):
    return asyncio.run(coro)


def configure(monkeypatch, servers: str):
    monkeypatch.setattr(service, "settings", SimpleNamespace(mcp_servers=servers))
    service.reset_cache()


@pytest.fixture(autouse=True)
def clean_cache():
    service.reset_cache()
    yield
    service.reset_cache()


# --- Configuracao ----------------------------------------------------------


def test_empty_config_means_no_mcp(monkeypatch):
    configure(monkeypatch, "")

    assert service._parse_servers() == {}
    assert service.configured() is False
    assert run(service.get_tools()) == []


def test_map_form_is_accepted(monkeypatch):
    configure(monkeypatch, '{"fs": {"command": "npx", "args": ["-y", "srv"]}}')

    servers = service._parse_servers()

    assert list(servers) == ["fs"]
    assert servers["fs"]["command"] == "npx"


def test_list_form_is_normalised_to_a_map(monkeypatch):
    configure(
        monkeypatch,
        '[{"name": "docs", "url": "http://localhost:3000/mcp"}]',
    )

    servers = service._parse_servers()

    assert list(servers) == ["docs"]
    assert servers["docs"]["url"] == "http://localhost:3000/mcp"


def test_stdio_transport_is_inferred_from_command(monkeypatch):
    configure(monkeypatch, '{"fs": {"command": "npx"}}')

    assert service._parse_servers()["fs"]["transport"] == "stdio"


def test_http_transport_is_inferred_from_url(monkeypatch):
    configure(monkeypatch, '{"docs": {"url": "http://localhost:3000/mcp"}}')

    assert service._parse_servers()["docs"]["transport"] == "streamable_http"


def test_explicit_transport_is_kept(monkeypatch):
    configure(
        monkeypatch,
        '{"docs": {"url": "http://x/mcp", "transport": "sse"}}',
    )

    assert service._parse_servers()["docs"]["transport"] == "sse"


def test_invalid_json_degrades_to_no_servers(monkeypatch):
    configure(monkeypatch, "{isso nao e json}")

    assert service._parse_servers() == {}


def test_non_object_config_is_rejected(monkeypatch):
    configure(monkeypatch, '"apenas-uma-string"')

    assert service._parse_servers() == {}


# --- Conexao ---------------------------------------------------------------


def test_unreachable_server_returns_no_tools(monkeypatch):
    configure(monkeypatch, '{"fs": {"command": "nao-existe"}}')

    class _Client:
        def __init__(self, servers):
            pass

        async def get_tools(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _Client
    )

    assert run(service.get_tools()) == []


def test_failure_is_cached_to_avoid_reconnecting_every_message(monkeypatch):
    configure(monkeypatch, '{"fs": {"command": "nao-existe"}}')
    attempts = []

    class _Client:
        def __init__(self, servers):
            attempts.append(servers)

        async def get_tools(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _Client
    )

    run(service.get_tools())
    run(service.get_tools())

    assert len(attempts) == 1


def test_tools_are_returned_and_cached(monkeypatch):
    configure(monkeypatch, '{"fs": {"command": "npx"}}')
    tool = SimpleNamespace(name="read_file")
    attempts = []

    class _Client:
        def __init__(self, servers):
            attempts.append(servers)

        async def get_tools(self):
            return [tool]

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _Client
    )

    assert run(service.get_tools()) == [tool]
    assert run(service.get_tools()) == [tool]
    assert len(attempts) == 1


def test_force_bypasses_the_cache(monkeypatch):
    configure(monkeypatch, '{"fs": {"command": "npx"}}')
    attempts = []

    class _Client:
        def __init__(self, servers):
            attempts.append(servers)

        async def get_tools(self):
            return []

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _Client
    )

    run(service.get_tools())
    run(service.get_tools(force=True))

    assert len(attempts) == 2


# --- Status ----------------------------------------------------------------


def test_status_without_configuration(monkeypatch):
    configure(monkeypatch, "")

    assert run(service.status()) == {
        "configured": False, "servers": [], "tools": 0
    }


def test_status_lists_servers_and_tool_names(monkeypatch):
    configure(monkeypatch, '{"fs": {"command": "npx"}}')

    class _Client:
        def __init__(self, servers):
            pass

        async def get_tools(self):
            return [SimpleNamespace(name="read_file")]

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _Client
    )

    status = run(service.status())

    assert status["configured"] is True
    assert status["servers"] == ["fs"]
    assert status["tool_names"] == ["read_file"]
    assert status["error"] is None
