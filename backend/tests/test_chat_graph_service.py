import asyncio

import pytest

from langchain_core.messages import AIMessage, SystemMessage

from app.models.schemas import (
    LLMResponse,
    LaunchAction,
    ResponseModeEnum,
    ShortcutType,
)
from app.orchestration.nodes import action_detection
from app.services import (
    assistant_tools,
    calendar_query_service,
    chat_graph_service,
    llm_routing_service,
)
from app.services.calendar_query_service import CalendarQueryPlan, CalendarQueryResult

pytestmark = pytest.mark.integration


def _system_of(messages) -> str:
    """O prompt de sistema que chegou ao modelo, ja montado pelo grafo."""
    return "\n".join(
        str(item.content) for item in messages if isinstance(item, SystemMessage)
    )


def answering(content: str):
    """Stub de um passo do modelo: responde em texto, sem chamar ferramenta."""

    async def invoke_model(provider, messages, tools=()):
        return (
            AIMessage(content=content),
            LLMResponse(llm=provider, content=content),
        )

    return invoke_model


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
            user_id="user-1",
        )
    )


def test_chat_graph_exposes_explicit_workflow_nodes():
    nodes = set(chat_graph_service.chat_graph.get_graph().nodes)

    assert {
        "detect_action",
        "resolve_shortcut",
        "retrieve_context",
        "acknowledge_action",
        "query_calendar",
        "dispatch_single",
        "dispatch_multi",
        "dispatch_chain",
    }.issubset(nodes)


def test_computer_action_short_circuits_llm_dispatch(monkeypatch):
    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("LLM dispatch should not run for a local action")

    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
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


def test_workspace_context_message_skips_action_detection_and_goes_to_llm(
    monkeypatch,
):
    async def rank_providers(candidates, task="general", available_only=False):
        return ["gpt"]

    monkeypatch.setattr(
        chat_graph_service.agent_service, "rank_auto_llms", rank_providers
    )
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "invoke_model",
        answering("Analise do arquivo."),
    )

    # Blob de contexto com gatilhos que antes disparavam acoes locais:
    # "ip" no codigo (diagnostico de rede) e "vscode" no caminho (atalho).
    message = (
        "Contexto local do workspace capturado pela interface.\n"
        "Acao: Contexto automatico do workspace selecionado\n"
        "Caminho: C:\\Users\\dev\\vscode-projects\\crafter-gestor\n"
        "--- server.js ---\n"
        "app.set('trust proxy', 1); // usa req.ip\n\n"
        "Pedido original do usuario:\n"
        "Analise e edite o arquivo index.html para citar o produto.\n"
    )
    result = run_graph(message=message, active_llms=["gpt"])

    assert result["action_kind"] == "chat"
    assert result.get("action") is None
    assert result["responses"][0].content == "Analise do arquivo."


def test_local_action_result_skips_action_detection_and_goes_to_llm(
    monkeypatch,
):
    async def rank_providers(candidates, task="general", available_only=False):
        return ["gpt"]

    monkeypatch.setattr(
        chat_graph_service.agent_service, "rank_auto_llms", rank_providers
    )
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "invoke_model",
        answering("Sua rede esta ok."),
    )

    # Resultado que a interface manda de volta para analise. O "api" de
    # `api.ipify.org` somado ao "Analise" do cabecalho fazia o detector de
    # codigo propor "Inspecionar workspace local" depois de cada diagnostico.
    message = (
        'Resultado da acao local "Diagnostico de rede" executada neste'
        " computador.\n"
        "Analise os dados abaixo, destaque problemas provaveis e diga os"
        " proximos passos praticos.\n\n"
        "--- IP externo ---\n"
        "Comando: GET https://api.ipify.org\n"
        "Exit code: 0\n"
        "STDOUT:\n"
        "170.78.32.127\n"
    )
    result = run_graph(message=message, active_llms=["gpt"])

    assert result["action_kind"] == "chat"
    assert result.get("action") is None
    assert result["responses"][0].content == "Sua rede esta ok."


def test_calendar_classifier_cannot_swallow_a_deterministic_action(monkeypatch):
    """Agenda e o unico detector que pergunta a um modelo - e ele le o historico.

    Depois de uma pergunta de agenda, o classificador passava a rotular tudo como
    calendario: "verifique meu IP" voltava como "nao encontrei conta de
    calendario", e a resposta errada realimentava o historico. Aqui ele erra de
    proposito; o diagnostico de rede tem que ganhar mesmo assim.
    """

    async def sempre_calendario(*args, **kwargs):
        return CalendarQueryResult(
            plan=CalendarQueryPlan(intent="list", days=1),
            events=[],
            answer="Nao encontrei uma conta de calendario conectada.",
        )

    monkeypatch.setattr(
        calendar_query_service, "interpret_calendar_query", sempre_calendario
    )

    result = run_graph(
        message="Como verificar meu IP, configuracoes de rede e diagnostico "
                "de conexao?",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "computer"
    assert result["action"]["action_id"] == "network_diagnostics"


def test_registration_tool_routes_structured_action_to_interface():
    result = run_graph(
        message="Cadastre o Notepad como bloco",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "registration"
    assert result["action"]["type"] == "register_shortcut"
    assert result["responses"][0].llm == "backend"
    assert "cadastrar o atalho" in result["responses"][0].content


def test_asking_for_a_script_goes_to_the_llm_instead_of_registering_a_shortcut(
    monkeypatch,
):
    async def rank_providers(candidates, task="general", available_only=False):
        return ["gpt"]

    monkeypatch.setattr(
        chat_graph_service.agent_service, "rank_auto_llms", rank_providers
    )
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "invoke_model",
        answering("Segue o script."),
    )

    result = run_graph(
        message="Crie um script para backup automatico de arquivos "
                "importantes, multiplataforma.",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "chat"
    assert result.get("action") is None
    assert result["responses"][0].content == "Segue o script."


def test_lesson_start_routes_to_education_interface_without_calling_llm(monkeypatch):
    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("LLM dispatch should not run for an interface action")

    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_single",
        fail_dispatch,
    )

    result = run_graph(
        message="Dani, vamos iniciar a aula",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "education"
    assert result["action"]["type"] == "education_open"
    assert result["action"]["destination"] == "lesson"
    assert "Modo Aula" in result["responses"][0].content


def test_calendar_action_short_circuits_llm_and_requests_confirmation(monkeypatch):
    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("LLM dispatch should not run for a calendar action")

    monkeypatch.setattr(
        assistant_tools,
        "invoke_calendar_action_tool",
        lambda message, timezone: {
            "type": "calendar_create",
            "title": "Consulta",
            "start_time": "2026-08-10T14:00:00-03:00",
            "end_time": "2026-08-10T15:00:00-03:00",
            "timezone": timezone,
            "provider": "google",
            "requires_confirmation": True,
        },
    )
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_single",
        fail_dispatch,
    )

    result = run_graph(
        message="Agende uma consulta",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "calendar"
    assert result["action"]["requires_confirmation"] is True
    assert "10 de agosto de 2026" in result["responses"][0].content
    assert "14 horas" in result["responses"][0].content
    assert "detalhes estão prontos" in result["responses"][0].content


def test_calendar_query_uses_interpreter_and_real_events_without_chat_hallucination(
    monkeypatch,
):
    async def interpret(*args, **kwargs):
        return CalendarQueryPlan(
            start_time="2026-08-06T00:00:00-03:00",
            end_time="2026-08-07T00:00:00-03:00",
            interpreted_by="gpt",
        )

    async def execute(user_id, plan):
        assert user_id == "user-1"
        return CalendarQueryResult(
            connected_accounts=1,
            events=[],
        )

    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("Normal chat dispatch must not answer calendar data")

    monkeypatch.setattr(
        calendar_query_service, "interpret_calendar_query", interpret
    )
    monkeypatch.setattr(
        calendar_query_service, "execute_calendar_query", execute
    )
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_single",
        fail_dispatch,
    )

    result = run_graph(
        message="O que tenho na agenda amanhã?",
        active_llms=["gpt"],
    )

    assert result["action_kind"] == "calendar_query"
    assert result.get("action") is None
    assert "não tem eventos" in result["responses"][0].content


def test_single_route_chooses_provider_and_dispatches(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def rank_providers(candidates, task="general", available_only=False):
        assert candidates == ["llama", "gpt"]
        assert task == "general"
        assert available_only is True
        return ["llama", "gpt"]

    async def invoke_model(provider, messages, tools=()):
        assert provider == "llama"
        assert messages[-1].content == "Ola"
        assert _system_of(messages).startswith("system")
        return (
            AIMessage(content="Resposta local"),
            LLMResponse(llm=provider, content="Resposta local"),
        )

    monkeypatch.setattr(action_detection, "lookup_shortcut", no_shortcut)
    monkeypatch.setattr(
        chat_graph_service.agent_service, "rank_auto_llms", rank_providers
    )
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "invoke_model",
        invoke_model,
    )

    result = run_graph(active_llms=["llama", "gpt"])

    assert result["action_kind"] == "chat"
    assert result["responses"] == [
        LLMResponse(llm="llama", content="Resposta local")
    ]
    assert result["agent_id"] == "general"
    # A chave existe valendo None de proposito: o checkpoint atravessa
    # mensagens, e omiti-la deixava a acao da rodada anterior sobreviver.
    assert result["action"] is None


def test_multi_route_dispatches_all_active_providers(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def dispatch(llms, message, history, system_prompt):
        assert llms == ["gpt", "claude"]
        return [
            LLMResponse(llm="gpt", content="A"),
            LLMResponse(llm="claude", content="B"),
        ]

    async def rank(llms, task="general", available_only=False):
        assert available_only is True
        return llms

    monkeypatch.setattr(action_detection, "lookup_shortcut", no_shortcut)
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_multi",
        dispatch,
    )
    monkeypatch.setattr(llm_routing_service, "rank_auto_llms", rank)

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

    async def rank(llms, task="general", available_only=False):
        assert available_only is True
        return llms

    monkeypatch.setattr(action_detection, "lookup_shortcut", no_shortcut)
    monkeypatch.setattr(
        chat_graph_service.langchain_agent_service,
        "dispatch_chain",
        dispatch,
    )
    monkeypatch.setattr(llm_routing_service, "rank_auto_llms", rank)

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

    async def invoke_model(provider, messages, tools=()):
        assert "system\nlaunch context" in _system_of(messages)
        return (
            AIMessage(content="Abrindo."),
            LLMResponse(llm=provider, content="Abrindo."),
        )

    monkeypatch.setattr(action_detection, "lookup_shortcut", find_shortcut)
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "invoke_model",
        invoke_model,
    )

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

    monkeypatch.setattr(action_detection, "lookup_shortcut", no_shortcut)

    result = run_graph()

    assert result["responses"][0].llm == "backend"
    assert result["responses"][0].is_error is True
    assert "Nenhum agente de IA" in result["responses"][0].content


def test_unexpected_graph_failure_returns_controlled_error(monkeypatch):
    async def fail_graph(_state):
        raise RuntimeError("provider connection failed")

    monkeypatch.setattr(chat_graph_service.chat_graph, "ainvoke", fail_graph)

    result = run_graph(
        requested_llm="gpt",
        active_llms=["gpt"],
    )

    assert result["action"] is None
    assert result["responses"][0].llm == "gpt"
    assert result["responses"][0].is_error is True
    assert "Tente novamente" in result["responses"][0].content


def _publish_machine(monkeypatch, *capability_ids: str):
    """Simula uma maquina conectada que publicou aquelas capacidades."""
    from app.services import device_catalog_service
    from app.services.client_capability_service import parse_manifest

    catalog = device_catalog_service.DeviceCatalog()
    catalog.publish(
        parse_manifest(
            {
                "platform": "windows",
                "capabilities": [
                    {
                        "id": capability_id,
                        "name": capability_id,
                        "description": f"Faz {capability_id} nesta maquina.",
                        "args_schema": {"type": "object"},
                    }
                    for capability_id in capability_ids
                ],
            },
            device_id="maquina-1",
        ),
        lambda manifest, capability: _noop_runner,
    )
    monkeypatch.setattr(
        device_catalog_service, "get_device_catalog", lambda: catalog
    )
    return device_catalog_service.bind_device("maquina-1")


async def _noop_runner(args):
    return ""


def test_shortcut_still_answers_for_a_capability_the_machine_declares(
    monkeypatch,
):
    from app.services import device_catalog_service

    token = _publish_machine(monkeypatch, "network_diagnostics")
    try:
        result = run_graph(
            message="Verifique meu IP e o diagnostico de rede",
            active_llms=["gpt"],
        )
    finally:
        device_catalog_service.reset_device(token)

    assert result["action_kind"] == "computer"
    assert result["action"]["action_id"] == "network_diagnostics"


def test_shortcut_does_not_propose_what_the_machine_cannot_do(monkeypatch):
    """A maquina publicou catalogo e o diagnostico de rede nao esta nele."""
    from app.services import device_catalog_service

    async def rank_providers(candidates, task="general", available_only=False):
        return ["gpt"]

    monkeypatch.setattr(
        chat_graph_service.agent_service, "rank_auto_llms", rank_providers
    )
    monkeypatch.setattr(
        chat_graph_service.agent_service.langchain_agent_service,
        "invoke_model",
        answering("Nao consigo diagnosticar a rede daqui."),
    )

    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    monkeypatch.setattr(action_detection, "lookup_shortcut", no_shortcut)

    token = _publish_machine(monkeypatch, "inspect_workspace")
    try:
        result = run_graph(
            message="Verifique meu IP e o diagnostico de rede",
            active_llms=["gpt"],
        )
    finally:
        device_catalog_service.reset_device(token)

    # Sem acao chumbada: a conversa segue para o modelo, que escolhe dentro do
    # catalogo que aquela maquina publicou.
    assert result["action_kind"] == "chat"
    assert result.get("action") is None
