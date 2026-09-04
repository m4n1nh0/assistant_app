"""O catalogo que a maquina do usuario publica, sem precisar de maquina.

O `runner_factory` e o ponto onde o transporte entra; aqui ele e um dublê, e e
justamente isso que permite testar registro, escopo e validacao sem WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from app.orchestration.agents import mcp_scopes
from app.services.client_capability_service import (
    ClientManifestError,
    client_descriptors,
    parse_manifest,
    register_client_capabilities,
    unregister_client_capabilities,
)
from app.toolkit.registry import ToolRegistry

MANIFEST = {
    "platform": "windows",
    "capabilities": [
        {
            "id": "network_diagnostics",
            "name": "Diagnostico de rede",
            "description": "Coleta IP, gateway, DNS e ping desta maquina.",
            "args_schema": {"type": "object", "properties": {}},
        },
        {
            "id": "run_script",
            "name": "Executar script local",
            "description": "Executa um script no shell da maquina.",
            "args_schema": {
                "type": "object",
                "required": ["script"],
                "properties": {"script": {"type": "string"}},
            },
            "risk_level": "medium",
            "requires_confirmation": True,
            "read_only": False,
        },
    ],
}


def _runner_factory(echo=None):
    def factory(manifest, capability):
        async def _run(args):
            if echo is not None:
                echo.append((manifest.device_id, capability.tool_name, args))
            return {"ok": True, "capability": capability.id}

        return _run

    return factory


def test_manifest_becomes_remote_tools_scoped_to_outside_capable_agents():
    registry = ToolRegistry()
    manifest = parse_manifest(MANIFEST, device_id="maquina-1")

    published = register_client_capabilities(
        registry, manifest, _runner_factory()
    )

    assert published == 2
    names = registry.names()
    assert names == {"local_network_diagnostics", "local_run_script"}

    descriptor = registry.get("local_run_script").descriptor
    assert descriptor.source == "remote"
    assert descriptor.server == "maquina-1"
    assert descriptor.read_only is False
    # Capacidade vinda de fora do processo segue a mesma politica do MCP.
    assert descriptor.scopes == mcp_scopes()


def test_description_tells_the_model_where_it_runs():
    registry = ToolRegistry()
    manifest = parse_manifest(MANIFEST, device_id="maquina-1")
    register_client_capabilities(registry, manifest, _runner_factory())

    description = registry.get("local_network_diagnostics").descriptor.description

    assert "maquina do usuario" in description
    assert "windows" in description


def test_runner_reaches_the_declaring_machine():
    registry = ToolRegistry()
    echo: list[tuple[str, str, dict]] = []
    manifest = parse_manifest(MANIFEST, device_id="maquina-1")
    register_client_capabilities(registry, manifest, _runner_factory(echo))

    result = asyncio.run(
        registry.get("local_run_script").runner({"script": "ls"})
    )

    assert result == {"ok": True, "capability": "run_script"}
    assert echo == [("maquina-1", "local_run_script", {"script": "ls"})]


def test_republish_replaces_the_previous_catalog_of_that_machine():
    registry = ToolRegistry()
    register_client_capabilities(
        registry, parse_manifest(MANIFEST, device_id="maquina-1"),
        _runner_factory(),
    )

    shrunk = {"platform": "windows", "capabilities": MANIFEST["capabilities"][:1]}
    register_client_capabilities(
        registry, parse_manifest(shrunk, device_id="maquina-1"),
        _runner_factory(),
    )

    # O que sumiu do manifesto tem que sumir do catalogo, ou o modelo continua
    # oferecendo uma capacidade que a maquina nao tem mais.
    assert registry.names() == {"local_network_diagnostics"}


def test_machines_do_not_erase_each_other():
    registry = ToolRegistry()
    register_client_capabilities(
        registry, parse_manifest(MANIFEST, device_id="maquina-1"),
        _runner_factory(),
    )
    other = {
        "platform": "macos",
        "capabilities": [
            {
                "id": "system_diagnostics",
                "name": "Diagnostico do sistema",
                "description": "Coleta memoria e disco.",
                "args_schema": {"type": "object"},
            }
        ],
    }
    register_client_capabilities(
        registry, parse_manifest(other, device_id="maquina-2"), _runner_factory()
    )

    assert len(registry) == 3
    assert len(client_descriptors(registry, device_id="maquina-2")) == 1

    unregister_client_capabilities(registry, "maquina-1")

    assert registry.names() == {"local_system_diagnostics"}


def test_broken_entry_does_not_take_down_the_rest():
    payload = {
        "platform": "linux",
        "capabilities": [
            {"id": "SEM MAIUSCULA", "description": "x", "args_schema": {}},
            {"id": "sem_descricao", "description": "  "},
            {
                "id": "boa",
                "description": "Faz algo util nesta maquina.",
                "args_schema": {"type": "object"},
            },
        ],
    }

    manifest = parse_manifest(payload, device_id="maquina-1")

    assert [item.id for item in manifest.capabilities] == ["boa"]
    assert len(manifest.rejected) == 2


def test_write_capability_without_confirmation_is_forced_to_confirm():
    payload = {
        "platform": "windows",
        "capabilities": [
            {
                "id": "apaga_tudo",
                "description": "Remove arquivos da maquina.",
                "args_schema": {"type": "object"},
                "read_only": False,
                "requires_confirmation": False,
            }
        ],
    }

    manifest = parse_manifest(payload, device_id="maquina-1")

    # Cliente velho ou adulterado nao ganha execucao silenciosa.
    assert manifest.capabilities[0].requires_confirmation is True


def test_envelope_without_capabilities_is_refused():
    with pytest.raises(ClientManifestError):
        parse_manifest({"platform": "windows"}, device_id="maquina-1")

    with pytest.raises(ClientManifestError):
        parse_manifest(MANIFEST, device_id="   ")


@pytest.mark.contract
def test_manifest_published_by_the_interface_is_accepted_here():
    """O catalogo real do Dart precisa passar no parser do Python.

    Sem isto, os dois lados so descobrem que discordam quando uma capacidade
    nova simplesmente nao aparece para o modelo em producao.
    """
    contract = (
        pathlib.Path(__file__).resolve().parents[2]
        / "contracts"
        / "local_capability_manifest.json"
    )
    payload = json.loads(contract.read_text(encoding="utf-8"))

    manifest = parse_manifest(payload, device_id="maquina-do-contrato")

    assert manifest.rejected == ()
    assert len(manifest.capabilities) == len(payload["capabilities"])

    registry = ToolRegistry()
    published = register_client_capabilities(
        registry, manifest, _runner_factory()
    )

    assert published == len(payload["capabilities"])
    assert "local_network_diagnostics" in registry.names()
    # O que escreve na maquina chega aqui exigindo confirmacao.
    assert registry.get("local_run_script").descriptor.read_only is False
