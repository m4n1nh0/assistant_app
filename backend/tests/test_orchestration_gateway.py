"""Orquestracao local x agent-orchestrator: o mesmo turno, o mesmo resultado.

A promessa de `ORCHESTRATOR_TRANSPORT` e a mesma de ferramentas e MCP: trocar
o transporte nao muda o comportamento. Os testes de contrato rodam a mesma
asserção pelos dois gateways, com o remoto falando HTTP de verdade com o
entrypoint do orquestrador (em memoria, sem porta).

Alem do contrato, ficam aqui as tres travessias que justificavam nao extrair o
servico - credenciais, maquina do usuario e autenticacao -, cada uma com o seu
caso de falha.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.devices.callback import DeviceCapabilityCallback
from app.adapters.orchestration.local import LocalOrchestrationGateway
from app.adapters.orchestration.remote import RemoteOrchestrationGateway
from app.adapters.orchestration.wire import (
    action_from_payload,
    manifest_from_payload,
    manifest_to_payload,
)
from app.adapters.tools.remote import RemoteToolGateway
from app.core.config import get_settings
from app.models.schemas import LaunchAction, LLMResponse, Message, ResponseModeEnum, ShortcutType
from app.ports.orchestration import ChatTurn
from shared.ports.tools import ToolInvocation, ToolTimeout
from app.services.client_capability_service import parse_manifest
from app.services.device_catalog_service import (
    DeviceCatalog,
    bind_device,
    current_device,
    get_device_catalog,
    reset_device,
    reset_device_catalog,
)
from app.services.remote_capability_gateway import RemoteCapabilityError
from app.services.user_llm_config_service import UserLLMRuntime, current_user_llms

pytestmark = pytest.mark.contract

TOKEN = "segredo-interno"
DEVICE = "user-1:sessao-1"


def run(coro):
    return asyncio.run(coro)


def asgi_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://contract"
    )


def _manifest(capability_id: str = "open_app", *, read_only: bool = True):
    return parse_manifest(
        {
            "platform": "windows",
            "capabilities": [
                {
                    "id": capability_id,
                    "name": "Abrir aplicativo",
                    "description": "Abre um aplicativo na maquina.",
                    "args_schema": {"type": "object", "properties": {}},
                    "read_only": read_only,
                    "requires_confirmation": not read_only,
                }
            ],
        },
        device_id=DEVICE,
    )


def _turn(**overrides) -> ChatTurn:
    values = {
        "message": "Abra o navegador",
        "history": [Message(role="user", content="oi")],
        "mode": ResponseModeEnum.single,
        "requested_llm": "gpt",
        "active_llms": ("gpt", "localai"),
        "system_prompt": "Voce e a assistente.",
        "tutor_id": "tutor-1",
        "user_id": "user-1",
        "conversation_id": "sessao-1",
    }
    values.update(overrides)
    return ChatTurn(**values)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Token configurado, catalogo de maquinas limpo e credencial sem banco."""
    from services.orchestrator import main as orchestrator

    monkeypatch.setattr(get_settings(), "internal_service_token", TOKEN)
    reset_device_catalog()

    loaded: list[str] = []

    async def fake_runtime(tutor_id):
        loaded.append(tutor_id)
        return UserLLMRuntime(
            scope=f"tutor:{tutor_id}",
            providers={"gpt": {"api_key": "sk-do-banco", "model": "gpt-4o", "enabled": True}},
        )

    monkeypatch.setattr(orchestrator, "load_user_llm_runtime", fake_runtime)
    yield loaded
    reset_device_catalog()


def _stub_graph(monkeypatch, seen: list[dict]):
    """Troca o grafo pelos dois caminhos e registra o que ele enxergou."""
    import app.orchestration.graph as graph_module
    from services.orchestrator import main as orchestrator

    async def fake_graph(**kwargs):
        runtime = current_user_llms()
        seen.append(
            {
                "kwargs": kwargs,
                "runtime_scope": runtime.scope if runtime else None,
                "device": current_device(),
                "tools": [item.name for item in get_device_catalog().descriptors()],
            }
        )
        return {
            "action_kind": "launch",
            "responses": [LLMResponse(llm="gpt", content="Abrindo.")],
            "action": LaunchAction(
                shortcut_id="shortcut-1",
                name="Navegador",
                target="browser",
                target_type=ShortcutType.app,
            ),
            "agent_id": "general",
            "tool_trace": [{"tool": "open"}],
            "errors": [],
            "execution_id": kwargs["execution_id"] or "exec-1",
        }

    monkeypatch.setattr(graph_module, "run_chat_graph", fake_graph)
    monkeypatch.setattr(orchestrator, "run_chat_graph", fake_graph)


def _gateways(token: str = TOKEN, devices: DeviceCatalog | None = None):
    from services.orchestrator import main as orchestrator

    local = LocalOrchestrationGateway()
    remote = RemoteOrchestrationGateway(
        "http://contract",
        token=token,
        client=asgi_client(orchestrator.app),
        max_retries=0,
        devices=devices or DeviceCatalog(),
    )
    return local, remote


# --- contrato ----------------------------------------------------------------


@pytest.mark.parametrize("index", [0, 1], ids=["local", "remote"])
def test_result_is_the_same_through_both_transports(monkeypatch, index):
    seen: list[dict] = []
    _stub_graph(monkeypatch, seen)

    result = run(_gateways()[index].run_chat(_turn()))

    assert [item.content for item in result["responses"]] == ["Abrindo."]
    assert isinstance(result["responses"][0], LLMResponse)
    # A rota da API depende do tipo concreto da acao, nao de um dicionario.
    assert isinstance(result["action"], LaunchAction)
    assert result["action"].shortcut_id == "shortcut-1"
    assert result["agent_id"] == "general"
    assert seen[0]["kwargs"]["message"] == "Abra o navegador"
    assert seen[0]["kwargs"]["active_llms"] == ["gpt", "localai"]
    assert seen[0]["kwargs"]["history"][0].content == "oi"


def test_orchestrator_loads_credentials_from_the_database_not_the_wire(
    monkeypatch, isolated
):
    """As chaves do usuario nao viajam: o orquestrador as decifra pelo tutor."""
    seen: list[dict] = []
    _stub_graph(monkeypatch, seen)
    _, remote = _gateways()

    run(remote.run_chat(_turn()))

    assert isolated == ["tutor-1"]
    assert seen[0]["runtime_scope"] == "tutor:tutor-1"


def test_credentials_do_not_leak_past_the_turn(monkeypatch):
    seen: list[dict] = []
    _stub_graph(monkeypatch, seen)
    _, remote = _gateways()

    run(remote.run_chat(_turn()))

    assert current_user_llms() is None


# --- autenticacao ------------------------------------------------------------


def test_wrong_token_becomes_an_error_response_with_the_cause(monkeypatch):
    seen: list[dict] = []
    _stub_graph(monkeypatch, seen)
    _, remote = _gateways(token="outro")

    result = run(remote.run_chat(_turn()))

    assert seen == []
    assert result["responses"][0].is_error is True
    assert "INTERNAL_SERVICE_TOKEN diferente" in result["errors"][0]


def test_orchestrator_refuses_turns_without_a_configured_token(monkeypatch):
    """Token vazio fecha a rota em vez de abri-la."""
    from services.orchestrator import main as orchestrator

    monkeypatch.setattr(get_settings(), "internal_service_token", "")

    async def call():
        async with asgi_client(orchestrator.app) as client:
            return await client.post(
                "/orchestrate/chat", json={"message": "oi"}, headers={"X-Internal-Token": ""}
            )

    assert run(call()).status_code == 503


def test_health_stays_open_without_token():
    """A plataforma consulta o live sem cabecalho nenhum."""
    from services.orchestrator import main as orchestrator

    async def call():
        async with asgi_client(orchestrator.app) as client:
            return await client.get("/health/live")

    assert run(call()).status_code == 200


def test_unreachable_orchestrator_degrades_instead_of_raising():
    gateway = RemoteOrchestrationGateway(
        "http://127.0.0.1:9", token=TOKEN, max_retries=0, timeout_seconds=0.5
    )

    result = run(gateway.run_chat(_turn()))

    assert result["action"] is None
    assert result["responses"][0].is_error is True
    assert result["responses"][0].llm == "gpt"


# --- maquina do usuario ------------------------------------------------------


def test_device_capabilities_reach_the_orchestrator(monkeypatch):
    """O agente no orquestrador enxerga a maquina que publicou pela API."""
    seen: list[dict] = []
    _stub_graph(monkeypatch, seen)
    api_catalog = DeviceCatalog()
    api_catalog.publish(_manifest(), lambda manifest, capability: _never_called)
    _, remote = _gateways(devices=api_catalog)

    run(remote.run_chat(_turn(device_id=DEVICE)))

    assert seen[0]["device"] == DEVICE
    assert seen[0]["tools"] == ["local_open_app"]
    assert current_device() == ""


def test_disconnected_device_is_dropped_on_the_orchestrator(monkeypatch):
    seen: list[dict] = []
    _stub_graph(monkeypatch, seen)
    get_device_catalog().publish(_manifest(), lambda manifest, capability: _never_called)
    _, remote = _gateways(devices=DeviceCatalog())

    run(remote.run_chat(_turn(device_id=DEVICE)))

    assert seen[0]["tools"] == []


async def _never_called(args):
    raise AssertionError("runner da API nao deveria rodar no orquestrador")


def test_manifest_survives_the_wire():
    manifest = _manifest(read_only=False)

    rebuilt = manifest_from_payload(manifest_to_payload(manifest))

    assert rebuilt.device_id == manifest.device_id
    assert rebuilt.capabilities == manifest.capabilities


def test_unknown_action_type_stays_a_dict():
    """Orquestrador mais novo que a API no meio de um deploy nao derruba a rota."""
    payload = {"type": "acao_nova", "x": 1}

    assert action_from_payload(payload) == payload


# --- volta da capacidade pela API ---------------------------------------------


class _FakeCapabilities:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[dict] = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _callback(monkeypatch, outcome, *, token: str = TOKEN):
    from app.routers.internal import router

    fake = _FakeCapabilities(outcome)
    monkeypatch.setattr("app.routers.websocket.remote_capabilities", fake)
    api = FastAPI()
    api.include_router(router)
    get_device_catalog().publish(_manifest(), lambda manifest, capability: _never_called)
    callback = DeviceCapabilityCallback(
        "http://contract", token=token, client=asgi_client(api)
    )
    return callback, fake


def _invoke(callback, *, repeatable: bool = True, capability: str = "open_app"):
    return run(
        callback.call(
            device_id=DEVICE,
            tool_name=f"local_{capability}",
            capability_id=capability,
            args={"app": "notepad"},
            repeatable=repeatable,
        )
    )


def test_capability_output_comes_back_through_the_api(monkeypatch):
    callback, fake = _callback(monkeypatch, "Notepad aberto.")

    assert _invoke(callback) == "Notepad aberto."
    assert fake.calls[0]["device_id"] == DEVICE
    assert fake.calls[0]["args"] == {"app": "notepad"}


def test_repeatable_timeout_stays_retryable(monkeypatch):
    callback, _ = _callback(monkeypatch, ToolTimeout("maquina nao respondeu"))

    with pytest.raises(ToolTimeout):
        _invoke(callback)


def test_timeout_of_an_action_that_changes_the_machine_is_final(monkeypatch):
    callback, _ = _callback(monkeypatch, ToolTimeout("maquina nao respondeu"))

    with pytest.raises(RemoteCapabilityError):
        _invoke(callback, repeatable=False)


def test_api_refuses_a_capability_the_machine_did_not_publish(monkeypatch):
    callback, fake = _callback(monkeypatch, "nao deveria rodar")

    with pytest.raises(RemoteCapabilityError, match="nao publicou"):
        _invoke(callback, capability="run_script")
    assert fake.calls == []


def test_internal_route_rejects_a_wrong_token(monkeypatch):
    callback, fake = _callback(monkeypatch, "nao deveria rodar", token="outro")

    with pytest.raises(RemoteCapabilityError, match="HTTP 401"):
        _invoke(callback)
    assert fake.calls == []


# --- tool-service remoto -----------------------------------------------------


def test_remote_tool_gateway_keeps_the_user_machine():
    """Com TOOL_TRANSPORT=remote o agente perdia as capacidades da maquina."""
    devices = DeviceCatalog()

    def factory(manifest, capability):
        async def _run(args):
            return "executado na maquina"

        return _run

    devices.publish(_manifest(), factory)
    gateway = RemoteToolGateway(
        "http://127.0.0.1:9", max_retries=0, timeout_seconds=0.2, devices=devices
    )
    token = bind_device(DEVICE)
    try:
        names = [item.name for item in run(gateway.list_tools())]
        result = run(gateway.invoke(ToolInvocation(name="local_open_app")))
    finally:
        reset_device(token)

    assert names == ["local_open_app"]
    assert result.ok is True
    assert result.output == "executado na maquina"


# --- fachada usada pelas rotas -----------------------------------------------


def test_routes_facade_delivers_the_bound_device_to_the_gateway():
    from app.adapters import container
    from app.services import chat_graph_service

    received: list[ChatTurn] = []

    class Recording:
        async def run_chat(self, turn):
            received.append(turn)
            return {"responses": []}

        async def health(self):
            return {"ok": True}

    container.override(orchestration=Recording())
    token = bind_device(DEVICE)
    try:
        run(
            chat_graph_service.run_chat_graph(
                message="oi",
                history=[],
                mode=ResponseModeEnum.single,
                requested_llm=None,
                active_llms=["gpt"],
                system_prompt="",
                tutor_id="tutor-1",
            )
        )
    finally:
        reset_device(token)
        container.reset()

    assert received[0].device_id == DEVICE
    assert received[0].active_llms == ("gpt",)
