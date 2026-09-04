"""Isolamento entre maquinas conectadas.

O risco que estes testes guardam e concreto: `local_run_script` existe em toda
maquina, e um catalogo unico faria a segunda conexao sobrescrever a primeira -
a conversa de um usuario rodando script na maquina de outro.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.tools.local import LocalToolGateway
from app.ports.tools import ToolInvocation
from app.services.client_capability_service import parse_manifest
from app.services.device_catalog_service import (
    DeviceCatalog,
    bind_device,
    current_device,
    device_key,
    reset_device,
    session_device,
)
from app.toolkit.executor import ToolExecutor
from app.toolkit.registry import ToolRegistry


def _manifest(capability_id: str = "run_script") -> dict:
    return {
        "platform": "windows",
        "capabilities": [
            {
                "id": capability_id,
                "name": "Executar script local",
                "description": "Executa um script no shell da maquina.",
                "args_schema": {"type": "object", "properties": {}},
            }
        ],
    }


def _runner_factory(marker: str):
    def factory(manifest, capability):
        async def _run(args):
            return f"{marker}:{manifest.device_id}"

        return _run

    return factory


@pytest.fixture
def catalog():
    return DeviceCatalog()


@pytest.fixture
def bound():
    tokens = []

    def _bind(device_id: str):
        tokens.append(bind_device(device_id))

    yield _bind
    for token in reversed(tokens):
        reset_device(token)


def test_same_capability_name_on_two_machines_does_not_collide(catalog, bound):
    catalog.publish(
        parse_manifest(_manifest(), device_id="ana"), _runner_factory("ana")
    )
    catalog.publish(
        parse_manifest(_manifest(), device_id="bob"), _runner_factory("bob")
    )

    bound("ana")
    ana = catalog.find("local_run_script")
    assert asyncio.run(ana.runner({})) == "ana:ana"

    bound("bob")
    bob = catalog.find("local_run_script")
    assert asyncio.run(bob.runner({})) == "bob:bob"

    assert catalog.devices() == ["ana", "bob"]


def test_session_without_machine_sees_no_local_capability(catalog):
    catalog.publish(
        parse_manifest(_manifest(), device_id="ana"), _runner_factory("ana")
    )

    assert current_device() == ""
    assert catalog.descriptors() == []
    assert catalog.find("local_run_script") is None


def test_disconnect_removes_the_machine_catalog(catalog, bound):
    catalog.publish(
        parse_manifest(_manifest(), device_id="ana"), _runner_factory("ana")
    )
    bound("ana")

    assert catalog.drop("ana") == 1
    assert catalog.find("local_run_script") is None
    assert catalog.descriptors() == []


def test_republish_replaces_instead_of_accumulating(catalog, bound):
    catalog.publish(
        parse_manifest(_manifest(), device_id="ana"), _runner_factory("v1")
    )
    catalog.publish(
        parse_manifest(_manifest("network_diagnostics"), device_id="ana"),
        _runner_factory("v2"),
    )
    bound("ana")

    assert catalog.find("local_run_script") is None
    assert catalog.find("local_network_diagnostics") is not None


def test_gateway_merges_process_tools_with_the_session_machine(catalog, bound):
    registry = ToolRegistry()
    gateway = LocalToolGateway(
        registry,
        ToolExecutor(registry),
        devices=catalog,
    )
    catalog.publish(
        parse_manifest(_manifest(), device_id="ana"), _runner_factory("ana")
    )

    bound("ana")
    tools = asyncio.run(gateway.list_tools(agent_id="general"))
    assert [item.name for item in tools] == ["local_run_script"]

    result = asyncio.run(
        gateway.invoke(
            ToolInvocation(name="local_run_script", args={}, agent_id="general")
        )
    )
    assert result.ok is True
    assert result.output == "ana:ana"
    assert result.source == "remote"


def test_gateway_hides_other_machines_from_this_session(catalog, bound):
    registry = ToolRegistry()
    gateway = LocalToolGateway(registry, ToolExecutor(registry), devices=catalog)
    catalog.publish(
        parse_manifest(_manifest(), device_id="ana"), _runner_factory("ana")
    )

    # Sessao do Bob, que nao publicou nada: a maquina da Ana nao pode aparecer
    # nem ser invocavel.
    bound("bob")

    assert asyncio.run(gateway.list_tools(agent_id="general")) == []
    result = asyncio.run(
        gateway.invoke(
            ToolInvocation(name="local_run_script", args={}, agent_id="general")
        )
    )
    assert result.ok is False
    assert "desconhecida" in result.error


def test_http_session_finds_the_catalog_published_by_the_websocket(catalog):
    # O WebSocket registra o catalogo com a chave da conexao...
    catalog.publish(
        parse_manifest(_manifest(), device_id=device_key("ana", "default")),
        _runner_factory("ana"),
    )

    # ...e a rota HTTP do chat precisa achar exatamente aquele, ou a capacidade
    # e publicada e nunca encontrada.
    with session_device("ana", "default"):
        assert catalog.find("local_run_script") is not None

    assert catalog.find("local_run_script") is None
