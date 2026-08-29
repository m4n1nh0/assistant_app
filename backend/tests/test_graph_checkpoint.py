"""Persistencia, retomada e isolamento do estado do grafo.

O fluxo do chat sempre teve "retomada": a interface reenviava a conversa e o
backend recomecava do zero. Isso deixa de ser aceitavel quando a execucao ja
custou uma busca vetorial, chamadas de modelo e uma ferramenta.

O que se verifica aqui e que existe estado gravado de verdade, que ele e
recuperavel pela sessao, e que duas contas com o mesmo identificador de sessao
nao compartilham historico - esse ultimo e o que separa checkpoint util de
vazamento entre usuarios.
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from app.models.schemas import LLMResponse, ResponseModeEnum
from app.orchestration.checkpoint import build_checkpointer, thread_config
from app.orchestration.graph import build_chat_graph
from app.orchestration.nodes import action_detection
from app.orchestration.state import ChatRuntimeContext

pytestmark = pytest.mark.integration


def run(coro):
    return asyncio.run(coro)


class _Outcome:
    def __init__(self, content: str):
        self.response = LLMResponse(llm="llama", content=content)
        self.agent_id = "general"
        self.provider = "llama"
        self.tool_trace = []
        self.handoffs = []


@pytest.fixture
def graph_factory(monkeypatch):
    """Monta o grafo com colaboradores previsiveis sobre um checkpointer dado."""

    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def run_agents(**kwargs):
        return _Outcome("resposta do agente")

    monkeypatch.setattr(action_detection, "lookup_shortcut", no_shortcut)

    def _build(checkpointer):
        return build_chat_graph(run_agents=run_agents, checkpointer=checkpointer)

    return _build


@pytest.fixture
def graph(graph_factory):
    """Grafo com checkpointer em memoria."""
    return graph_factory(build_checkpointer("memory"))


def invoke(graph, *, conversation_id: str, tutor_id: str = "tutor-1", message="Ola"):
    return run(
        graph.ainvoke(
            {
                "message": message,
                "history": [],
                "mode": ResponseModeEnum.single,
                "system_prompt": "system",
                "tool_trace": [],
                "handoffs": [],
                "errors": [],
            },
            context=ChatRuntimeContext(
                active_llms=("llama",),
                tutor_id=tutor_id,
                conversation_id=conversation_id,
            ),
            config=thread_config(
                conversation_id=conversation_id, tenant_id=tutor_id
            ),
        )
    )


# --- Configuracao do checkpointer -------------------------------------------


def test_memory_backend_is_the_default():
    assert build_checkpointer("memory") is not None
    assert build_checkpointer("") is not None


def test_checkpointing_can_be_switched_off():
    assert build_checkpointer("none") is None


def test_unavailable_backend_falls_back_to_memory():
    """Backend faltando degrada, nunca impede o boot."""
    assert build_checkpointer("sqlite", sqlite_path="") is not None


def test_thread_config_isolates_tenants():
    a = thread_config(conversation_id="sessao-1", tenant_id="tutor-a")
    b = thread_config(conversation_id="sessao-1", tenant_id="tutor-b")

    # Mesma sessao, contas diferentes: a conta entra na chave da linha de
    # execucao, senao as duas leriam o mesmo checkpoint.
    assert a["configurable"]["thread_id"] != b["configurable"]["thread_id"]
    assert a["configurable"]["thread_id"].startswith("tutor-a:")


def test_thread_config_does_not_hijack_the_subgraph_namespace():
    """`checkpoint_ns` e reservado a subgrafos pelo LangGraph."""
    config = thread_config(conversation_id="sessao-1", tenant_id="tutor-a")

    assert "checkpoint_ns" not in config["configurable"]


def test_thread_config_survives_a_missing_session():
    assert thread_config(conversation_id="")["configurable"]["thread_id"]


# --- Estado gravado ---------------------------------------------------------


def test_execution_leaves_a_recoverable_checkpoint(graph):
    invoke(graph, conversation_id="sessao-1")

    snapshot = run(
        graph.aget_state(
            thread_config(conversation_id="sessao-1", tenant_id="tutor-1")
        )
    )

    assert snapshot.values["action_kind"] == "chat"
    assert snapshot.values["responses"][0].content == "resposta do agente"


def test_a_second_session_does_not_see_the_first(graph):
    invoke(graph, conversation_id="sessao-1", message="primeira")

    snapshot = run(
        graph.aget_state(
            thread_config(conversation_id="sessao-2", tenant_id="tutor-1")
        )
    )

    assert snapshot.values == {}


def test_same_session_of_another_tenant_is_isolated(graph):
    invoke(graph, conversation_id="sessao-1", tutor_id="tutor-a")

    snapshot = run(
        graph.aget_state(
            thread_config(conversation_id="sessao-1", tenant_id="tutor-b")
        )
    )

    assert snapshot.values == {}


def test_history_of_a_session_accumulates_checkpoints(graph):
    invoke(graph, conversation_id="sessao-1", message="primeira")
    invoke(graph, conversation_id="sessao-1", message="segunda")

    config = thread_config(conversation_id="sessao-1", tenant_id="tutor-1")

    async def _collect():
        return [item async for item in graph.aget_state_history(config)]

    assert len(run(_collect())) > 1


def test_finished_execution_has_nothing_pending(graph):
    invoke(graph, conversation_id="sessao-1")

    snapshot = run(
        graph.aget_state(
            thread_config(conversation_id="sessao-1", tenant_id="tutor-1")
        )
    )

    # Execucao concluida nao deixa no pendente: nao ha o que retomar.
    assert list(snapshot.next) == []


def test_graph_without_checkpointer_keeps_no_state(monkeypatch):
    async def no_shortcut(message, tutor_id):
        return None, "chat", ""

    async def run_agents(**kwargs):
        return _Outcome("sem memoria")

    monkeypatch.setattr(action_detection, "lookup_shortcut", no_shortcut)
    graph = build_chat_graph(run_agents=run_agents, checkpointer=None)

    result = invoke(graph, conversation_id="sessao-1")

    assert result["responses"][0].content == "sem memoria"
    with pytest.raises(Exception):
        run(
            graph.aget_state(
                thread_config(conversation_id="sessao-1", tenant_id="tutor-1")
            )
        )


# --- Fachada de retomada ----------------------------------------------------


def test_resume_reports_clearly_when_checkpointing_is_off(monkeypatch):
    from app.orchestration import graph as graph_module

    monkeypatch.setattr(graph_module, "chat_checkpointer", None)

    result = run(graph_module.resume_chat_graph(conversation_id="sessao-1"))

    assert result["responses"][0].is_error is True
    assert "desligado" in result["errors"][0]


def test_state_endpoint_reports_when_checkpointing_is_off(monkeypatch):
    from app.orchestration import graph as graph_module

    monkeypatch.setattr(graph_module, "chat_checkpointer", None)

    assert run(graph_module.graph_state(conversation_id="s"))["available"] is False


# --- Retencao limitada em memoria -------------------------------------------


def test_memory_saver_evicts_the_oldest_conversations(graph_factory):
    """O saver do LangGraph nunca descarta nada; o nosso precisa descartar."""
    from app.orchestration.checkpoint import BoundedMemorySaver

    saver = BoundedMemorySaver(max_threads=3)
    graph = graph_factory(saver)

    for index in range(6):
        invoke(graph, conversation_id=f"sessao-{index}")

    assert saver.retained_threads == 3
    assert len(saver.storage) == 3


def test_eviction_clears_every_store(graph_factory):
    """Limpar so `storage` deixaria `writes` e `blobs` crescendo sozinhos."""
    from app.orchestration.checkpoint import BoundedMemorySaver

    saver = BoundedMemorySaver(max_threads=1)
    graph = graph_factory(saver)

    invoke(graph, conversation_id="antiga")
    invoke(graph, conversation_id="nova")

    descartada = "tutor-1:antiga"
    assert descartada not in saver.storage
    assert not [k for k in saver.writes if k and k[0] == descartada]
    assert not [k for k in saver.blobs if k and k[0] == descartada]


def test_reading_a_conversation_protects_it_from_eviction(graph_factory):
    """Conversa ativa nao pode cair so por ser a mais antiga a ter escrito."""
    from app.orchestration.checkpoint import BoundedMemorySaver

    saver = BoundedMemorySaver(max_threads=2)
    graph = graph_factory(saver)

    invoke(graph, conversation_id="importante")
    invoke(graph, conversation_id="outra")
    # Ler renova a posicao da conversa na fila de uso.
    run(graph.aget_state(thread_config(conversation_id="importante", tenant_id="tutor-1")))
    invoke(graph, conversation_id="terceira")

    assert "tutor-1:importante" in saver.storage
    assert "tutor-1:outra" not in saver.storage


def test_retained_conversation_is_still_resumable(graph_factory):
    from app.orchestration.checkpoint import BoundedMemorySaver

    saver = BoundedMemorySaver(max_threads=5)
    graph = graph_factory(saver)
    invoke(graph, conversation_id="sessao-1")

    snapshot = run(
        graph.aget_state(thread_config(conversation_id="sessao-1", tenant_id="tutor-1"))
    )

    assert snapshot.values["responses"][0].content == "resposta do agente"
