"""A ida e volta ate a maquina do usuario, sem abrir socket.

O transporte e injetado, entao da para testar o que so acontece em producao:
resposta atrasada, maquina que cai no meio, timeout de acao que altera o
computador.
"""

from __future__ import annotations

import asyncio

import pytest

from app.ports.tools import ToolTimeout
from app.services.client_capability_service import (
    parse_manifest,
    register_client_capabilities,
)
from app.services.remote_capability_gateway import (
    RemoteCapabilityError,
    RemoteCapabilityGateway,
)
from app.toolkit.executor import ToolExecutor
from app.toolkit.registry import ToolRegistry
from app.ports.tools import ToolInvocation

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
            "args_schema": {"type": "object", "properties": {}},
            "risk_level": "medium",
            "requires_confirmation": True,
            "read_only": False,
        },
    ],
}


class FakeChannel:
    """Guarda o que foi empurrado para cada maquina."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.fail = fail

    async def send(self, device_id: str, payload: dict) -> None:
        if self.fail:
            raise ConnectionError("socket fechado")
        self.sent.append((device_id, payload))

    @property
    def last_call_id(self) -> str:
        return self.sent[-1][1]["payload"]["call_id"]


def test_call_reaches_the_machine_and_returns_its_text():
    channel = FakeChannel()
    gateway = RemoteCapabilityGateway(channel.send)

    async def scenario():
        task = asyncio.create_task(
            gateway.call(
                device_id="maquina-1",
                tool_name="local_network_diagnostics",
                capability_id="network_diagnostics",
                args={},
            )
        )
        await asyncio.sleep(0)  # deixa a chamada sair
        assert gateway.pending_calls == 1
        gateway.resolve(
            channel.last_call_id,
            {"ok": True, "prompt_text": "IP externo: 203.0.113.10"},
        )
        return await task

    output = asyncio.run(scenario())

    assert output == "IP externo: 203.0.113.10"
    device_id, message = channel.sent[0]
    assert device_id == "maquina-1"
    assert message["type"] == "tool_call"
    assert message["payload"]["capability_id"] == "network_diagnostics"


def test_machine_reporting_failure_becomes_tool_error():
    channel = FakeChannel()
    gateway = RemoteCapabilityGateway(channel.send)

    async def scenario():
        task = asyncio.create_task(
            gateway.call(
                device_id="maquina-1",
                tool_name="local_run_script",
                capability_id="run_script",
                args={},
                repeatable=False,
            )
        )
        await asyncio.sleep(0)
        gateway.resolve(
            channel.last_call_id,
            {"ok": False, "error": "usuario cancelou"},
        )
        await task

    with pytest.raises(RemoteCapabilityError, match="usuario cancelou"):
        asyncio.run(scenario())

    # A chamada sai do registro mesmo quando falha.
    assert gateway.pending_calls == 0


def test_read_only_timeout_is_retryable_write_timeout_is_not():
    channel = FakeChannel()
    gateway = RemoteCapabilityGateway(channel.send, default_timeout=0.01)

    async def call(repeatable: bool):
        return await gateway.call(
            device_id="maquina-1",
            tool_name="t",
            capability_id="c",
            args={},
            repeatable=repeatable,
        )

    with pytest.raises(ToolTimeout) as read_only:
        asyncio.run(call(True))
    assert read_only.value.retryable is True

    with pytest.raises(RemoteCapabilityError) as write:
        asyncio.run(call(False))
    # Repetir executaria o script duas vezes na maquina do usuario.
    assert write.value.retryable is False


def test_disconnect_releases_the_conversation_instead_of_hanging():
    channel = FakeChannel()
    gateway = RemoteCapabilityGateway(channel.send, default_timeout=30)

    async def scenario():
        task = asyncio.create_task(
            gateway.call(
                device_id="maquina-1",
                tool_name="local_network_diagnostics",
                capability_id="network_diagnostics",
                args={},
            )
        )
        await asyncio.sleep(0)
        assert gateway.cancel_device("maquina-1") == 1
        await task

    with pytest.raises(RemoteCapabilityError, match="conexao encerrada"):
        asyncio.run(scenario())


def test_late_or_unknown_answer_is_ignored():
    gateway = RemoteCapabilityGateway(FakeChannel().send)

    assert gateway.resolve("call-que-ninguem-espera", {"ok": True}) is False


def test_unreachable_machine_fails_before_waiting():
    gateway = RemoteCapabilityGateway(FakeChannel(fail=True).send)

    async def scenario():
        await gateway.call(
            device_id="maquina-1",
            tool_name="t",
            capability_id="c",
            args={},
        )

    with pytest.raises(RemoteCapabilityError, match="nao consegui falar"):
        asyncio.run(scenario())
    assert gateway.pending_calls == 0


def test_executor_runs_a_remote_capability_like_any_other_tool():
    """O ciclo completo: catalogo publicado, executor governando, WS no meio."""
    channel = FakeChannel()
    gateway = RemoteCapabilityGateway(channel.send)
    registry = ToolRegistry()
    register_client_capabilities(
        registry,
        parse_manifest(MANIFEST, device_id="maquina-1"),
        gateway.runner_factory(),
    )
    executor = ToolExecutor(registry, default_timeout=5)

    async def scenario():
        task = asyncio.create_task(
            executor.invoke(
                ToolInvocation(
                    name="local_network_diagnostics",
                    args={},
                    agent_id="code",
                )
            )
        )
        await asyncio.sleep(0)
        gateway.resolve(
            channel.last_call_id,
            {"ok": True, "prompt_text": "ipconfig: ..."},
        )
        return await task

    result = asyncio.run(scenario())

    assert result.ok is True
    assert result.output == "ipconfig: ..."
    # O agente nao sabe que a execucao aconteceu do outro lado do WebSocket;
    # a auditoria sabe.
    assert result.source == "remote"
