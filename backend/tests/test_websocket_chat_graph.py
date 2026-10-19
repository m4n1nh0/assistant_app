import asyncio

from app.models.schemas import LLMResponse, LaunchAction, ShortcutType
from app.routers import websocket as websocket_router


def test_websocket_chat_uses_graph_and_serializes_action(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def ready_llms():
        return ["gpt"]

    async def run_graph(**kwargs):
        assert kwargs["message"] == "Abra o navegador"
        assert kwargs["requested_llm"] == "gpt"
        assert kwargs["active_llms"] == ["gpt"]
        assert kwargs["tutor_id"] == "tutor-1"
        return {
            "responses": [LLMResponse(llm="gpt", content="Abrindo.")],
            "action": LaunchAction(
                shortcut_id="shortcut-1",
                name="Navegador",
                target="browser",
                target_type=ShortcutType.app,
            ),
        }

    async def send(session_id, data):
        sent.append((session_id, data))

    monkeypatch.setattr(websocket_router, "get_ready_llms", ready_llms)
    monkeypatch.setattr(websocket_router, "run_chat_graph", run_graph)
    monkeypatch.setattr(websocket_router.manager, "send", send)

    asyncio.run(
        websocket_router._handle_chat(
            "connection-1",
            {
                "message": "Abra o navegador",
                "mode": "single",
                "llm": "gpt",
                "history": [],
            },
            tutor_id="tutor-1",
        )
    )

    assert sent[0][1]["type"] == "thinking"
    response = sent[1][1]
    assert response["type"] == "chat_response"
    assert response["payload"]["responses"][0]["content"] == "Abrindo."
    assert response["payload"]["action"]["shortcut_id"] == "shortcut-1"


def _collect(monkeypatch, graph, payload, **kwargs):
    sent: list[dict] = []

    async def ready_llms():
        return ["gpt"]

    async def send(session_id, data):
        sent.append(data)

    monkeypatch.setattr(websocket_router, "get_ready_llms", ready_llms)
    monkeypatch.setattr(websocket_router, "stream_chat_graph", graph)
    monkeypatch.setattr(websocket_router.manager, "send", send)
    asyncio.run(websocket_router._handle_chat_stream("connection-1", payload, **kwargs))
    return sent


def test_websocket_chat_stream_relays_the_pieces_as_the_model_writes_them(monkeypatch):
    # O WebSocket nao conhece mais o cliente dos provedores: so o grafo fala com eles.
    assert not hasattr(websocket_router, "llm_service")

    async def graph(**kwargs):
        assert kwargs["message"] == "Oi"
        assert kwargs["tutor_id"] == "tutor-1" and kwargs["user_id"] == "user-1"
        yield {"type": "reset"}
        yield {"type": "delta", "text": "Ola, "}
        yield {"type": "delta", "text": "tudo bem?"}
        yield {"type": "final", "state": {"responses": [LLMResponse(llm="gpt", content="Ola, tudo bem?")], "action": None}}

    sent = _collect(monkeypatch, graph, {"message": "Oi", "llm": "gpt", "history": []},
                    tutor_id="tutor-1", user_id="user-1")

    assert [m["type"] for m in sent] == ["thinking", "stream_reset", "stream_chunk", "stream_chunk", "stream_end"]
    assert [m["payload"]["chunk"] for m in sent if m["type"] == "stream_chunk"] == ["Ola, ", "tudo bem?"]
    end = sent[-1]["payload"]
    assert end["full_response"] == "Ola, tudo bem?" and end["llm"] == "gpt" and end["done"] is True


def test_websocket_chat_stream_splits_the_final_text_when_nothing_was_live(monkeypatch):
    async def graph(**kwargs):
        text = "Ola, tudo bem? Esta resposta vem pronta do grafo e sai em pedacos."
        yield {"type": "final", "state": {"responses": [LLMResponse(llm="gpt", content=text)], "action": None}}

    sent = _collect(monkeypatch, graph, {"message": "Oi", "llm": "gpt"})

    chunks = [m["payload"]["chunk"] for m in sent if m["type"] == "stream_chunk"]
    assert len(chunks) > 1
    assert "".join(chunks) == "Ola, tudo bem? Esta resposta vem pronta do grafo e sai em pedacos."
    assert sent[-1]["payload"]["full_response"] == "".join(chunks)


def test_websocket_chat_stream_reports_graph_failure_as_error(monkeypatch):
    async def graph(**kwargs):
        raise RuntimeError("grafo caiu")
        yield  # pragma: no cover

    sent = _collect(monkeypatch, graph, {"message": "Oi"})

    assert sent[-1]["type"] == "error"
    assert "grafo caiu" in str(sent[-1])
